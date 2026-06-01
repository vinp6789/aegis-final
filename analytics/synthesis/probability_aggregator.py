from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any, Mapping, Protocol, Sequence

from analytics.common import clamp, clip_probability, normalize_timestamp


HORIZONS = (1, 3, 6, 9, 12)
FORECAST_TYPES = (
    "market_crash",
    "sector_stress",
    "liquidity_contraction",
    "crypto_risk_off",
    "systemic_stress",
)


class ProbabilityCalibrator(Protocol):
    def predict(self, probabilities: Sequence[float]) -> list[float]:
        ...


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


@dataclass(frozen=True)
class AggregatorInput:
    timestamp: datetime
    liquidity_index: float | None = None
    liquidity_transmission_score: float | None = None
    leading_diffusion_index: float | None = None
    hhi_concentration_score: float | None = None
    discovery_score: float | None = None
    backtest_sharpe: float | None = None
    backtest_win_rate: float | None = None
    regime_probability: float | None = None
    volatility_index: float | None = None
    crypto_liquidity_index: float | None = None
    previous_systemic_stress_12m: float | None = None


@dataclass(frozen=True)
class ProbabilityMatrix:
    timestamp: datetime
    probabilities: dict[str, dict[int, float]]
    early_warning_score: float
    confidence_score: float
    extreme_swing_detected: bool

    def vector(self, forecast_type: str) -> list[float]:
        return [self.probabilities[forecast_type][horizon] for horizon in HORIZONS]


class ProbabilityAggregator:
    def __init__(
        self,
        *,
        calibrators: Mapping[str, ProbabilityCalibrator] | None = None,
        swing_threshold: float = 0.35,
    ) -> None:
        if swing_threshold <= 0.0:
            raise ValueError("swing_threshold must be positive")
        self.calibrators = dict(calibrators or {})
        self.swing_threshold = swing_threshold

    def aggregate(self, input_data: AggregatorInput) -> ProbabilityMatrix:
        base = self._base_probabilities(input_data)
        calibrated = {
            forecast_type: self._calibrate(forecast_type, values)
            for forecast_type, values in base.items()
        }
        monotonic = {
            forecast_type: dict(zip(HORIZONS, pava_increasing(values)))
            for forecast_type, values in calibrated.items()
        }
        systemic_vector = [monotonic["systemic_stress"][horizon] for horizon in HORIZONS]
        ews = early_warning_score(monotonic)
        confidence = confidence_score(input_data, monotonic)
        previous = clean_probability(input_data.previous_systemic_stress_12m, default=systemic_vector[-1])
        swing = abs(systemic_vector[-1] - previous) >= self.swing_threshold
        return ProbabilityMatrix(
            timestamp=normalize_timestamp(input_data.timestamp),
            probabilities=monotonic,
            early_warning_score=round(ews, 6),
            confidence_score=round(confidence, 6),
            extreme_swing_detected=swing,
        )

    def aggregate_history(self, inputs: Sequence[AggregatorInput]) -> list[ProbabilityMatrix]:
        return [self.aggregate(input_data) for input_data in sorted(inputs, key=lambda item: item.timestamp)]

    def _base_probabilities(self, input_data: AggregatorInput) -> dict[str, list[float]]:
        liquidity = clean_probability(input_data.liquidity_index, default=50.0) / 100.0
        crypto_liquidity = clean_probability(input_data.crypto_liquidity_index, default=50.0) / 100.0
        transmission = clean_probability(input_data.liquidity_transmission_score, default=50.0) / 100.0
        breadth = clamp(clean_number(input_data.leading_diffusion_index, default=0.0), -1.0, 1.0)
        concentration = clamp(clean_number(input_data.hhi_concentration_score, default=0.25), 0.0, 1.0)
        discovery = clean_probability(input_data.discovery_score, default=50.0) / 100.0
        volatility = clean_probability(input_data.volatility_index, default=30.0) / 100.0
        regime = clip_probability(input_data.regime_probability, default=0.5)
        backtest_consistency = backtest_consistency_score(
            sharpe=input_data.backtest_sharpe,
            win_rate=input_data.backtest_win_rate,
        )

        liquidity_stress = 1.0 - liquidity
        breadth_stress = 1.0 - ((breadth + 1.0) / 2.0)
        crypto_stress = 1.0 - crypto_liquidity
        model_stress = 1.0 - backtest_consistency
        discovery_stress = discovery

        one_month = {
            "market_crash": weighted_sum(
                (breadth_stress, 0.30),
                (volatility, 0.25),
                (concentration, 0.15),
                (liquidity_stress, 0.15),
                (model_stress, 0.15),
            ),
            "sector_stress": weighted_sum(
                (breadth_stress, 0.35),
                (concentration, 0.30),
                (volatility, 0.20),
                (model_stress, 0.15),
            ),
            "liquidity_contraction": weighted_sum(
                (liquidity_stress, 0.45),
                (1.0 - transmission, 0.20),
                (volatility, 0.15),
                (regime, 0.20),
            ),
            "crypto_risk_off": weighted_sum(
                (crypto_stress, 0.40),
                (liquidity_stress, 0.20),
                (volatility, 0.20),
                (regime, 0.20),
            ),
            "systemic_stress": weighted_sum(
                (liquidity_stress, 0.25),
                (breadth_stress, 0.25),
                (concentration, 0.15),
                (volatility, 0.15),
                (discovery_stress, 0.10),
                (model_stress, 0.10),
            ),
        }
        return {
            forecast_type: horizon_curve(probability)
            for forecast_type, probability in one_month.items()
        }

    def _calibrate(self, forecast_type: str, probabilities: Sequence[float]) -> list[float]:
        clipped = [clamp(value, 0.0, 1.0) for value in probabilities]
        calibrator = self.calibrators.get(forecast_type)
        if calibrator is None:
            return clipped
        return [clamp(value, 0.0, 1.0) for value in calibrator.predict(clipped)]


def horizon_curve(one_month_probability: float) -> list[float]:
    base = clamp(one_month_probability, 0.0, 1.0)
    return [
        clamp(base, 0.0, 1.0),
        clamp(base + 0.06, 0.0, 1.0),
        clamp(base + 0.12, 0.0, 1.0),
        clamp(base + 0.17, 0.0, 1.0),
        clamp(base + 0.22, 0.0, 1.0),
    ]


def pava_increasing(values: Sequence[float]) -> list[float]:
    blocks: list[dict[str, float]] = []
    for value in values:
        blocks.append({"sum": clamp(value, 0.0, 1.0), "count": 1.0})
        while len(blocks) >= 2 and block_average(blocks[-2]) > block_average(blocks[-1]):
            right = blocks.pop()
            left = blocks.pop()
            blocks.append({"sum": left["sum"] + right["sum"], "count": left["count"] + right["count"]})
    output: list[float] = []
    for block in blocks:
        output.extend([round(clamp(block_average(block), 0.0, 1.0), 6)] * int(block["count"]))
    return output


def early_warning_score(probabilities: Mapping[str, Mapping[int, float]]) -> float:
    systemic = probabilities["systemic_stress"]
    crash = probabilities["market_crash"]
    liquidity = probabilities["liquidity_contraction"]
    crypto = probabilities["crypto_risk_off"]
    near_term = mean([systemic[1], crash[1], liquidity[1], crypto[1]])
    medium_term = mean([systemic[6], crash[6], liquidity[6], crypto[6]])
    momentum = max(0.0, systemic[12] - systemic[1])
    return clamp((near_term * 0.45 + medium_term * 0.40 + momentum * 0.15) * 100.0, 0.0, 100.0)


def confidence_score(
    input_data: AggregatorInput,
    probabilities: Mapping[str, Mapping[int, float]],
) -> float:
    one_month_values = [probabilities[name][1] for name in FORECAST_TYPES]
    agreement = 1.0 - min(pstdev(one_month_values), 0.5) / 0.5 if len(one_month_values) > 1 else 1.0
    backtest = backtest_consistency_score(
        sharpe=input_data.backtest_sharpe,
        win_rate=input_data.backtest_win_rate,
    )
    regime_stability = 1.0 - abs(clip_probability(input_data.regime_probability, default=0.5) - 0.5) * 0.6
    return clamp((agreement * 0.40 + backtest * 0.35 + regime_stability * 0.25) * 100.0, 0.0, 100.0)


def backtest_consistency_score(*, sharpe: float | None, win_rate: float | None) -> float:
    sharpe_component = clamp((clean_number(sharpe, default=0.0) + 1.0) / 3.0, 0.0, 1.0)
    win_component = clamp(clean_number(win_rate, default=0.5), 0.0, 1.0)
    return sharpe_component * 0.55 + win_component * 0.45


def weighted_sum(*values: tuple[float, float]) -> float:
    return clamp(sum(value * weight for value, weight in values), 0.0, 1.0)


def clean_number(value: float | int | None, *, default: float) -> float:
    if value is None:
        return default
    return float(value)


def clean_probability(value: float | int | None, *, default: float) -> float:
    return clamp(clean_number(value, default=default), 0.0, 100.0)


def block_average(block: Mapping[str, float]) -> float:
    return block["sum"] / block["count"]


class DiscoveryToProbabilityAdapter:
    def to_input(self, evaluation: Any) -> dict[str, float | None]:
        return {"discovery_score": getattr(evaluation, "current_score", None)}


class LiquidityToProbabilityAdapter:
    def to_input(self, snapshot: Any) -> dict[str, float | None]:
        return {
            "liquidity_index": getattr(snapshot, "global_liquidity_index", None),
            "liquidity_transmission_score": getattr(snapshot, "liquidity_transmission_score", None),
            "crypto_liquidity_index": getattr(snapshot, "crypto_liquidity_index", None),
        }


class BreadthToProbabilityAdapter:
    def to_input(self, breadth: Any, regime: Any | None = None) -> dict[str, float | None]:
        return {
            "leading_diffusion_index": getattr(breadth, "leading_diffusion_index", None),
            "hhi_concentration_score": getattr(breadth, "hhi_concentration_score", None),
            "regime_probability": getattr(regime, "regime_probability", None) if regime is not None else None,
        }


class WalkForwardToProbabilityAdapter:
    def to_input(self, backtest_stats: Any) -> dict[str, float | None]:
        return {
            "backtest_sharpe": getattr(backtest_stats, "sharpe", None),
            "backtest_win_rate": getattr(backtest_stats, "win_rate", None),
        }


class ProbabilityMatrixPersistenceAdapter:
    table_name = "probability_matrix_outputs_v3"

    def to_row(self, matrix: ProbabilityMatrix, *, target_scope: str = "GLOBAL") -> dict[str, Any]:
        systemic = matrix.probabilities["systemic_stress"]
        crypto = matrix.probabilities["crypto_risk_off"]
        return {
            "timestamp": matrix.timestamp,
            "target_scope": target_scope,
            "crash_prob_1m": matrix.probabilities["market_crash"][1],
            "crash_prob_3m": matrix.probabilities["market_crash"][3],
            "crash_prob_6m": matrix.probabilities["market_crash"][6],
            "crash_prob_9m": matrix.probabilities["market_crash"][9],
            "crash_prob_12m": matrix.probabilities["market_crash"][12],
            "pump_prob_1m": 1.0 - crypto[1],
            "pump_prob_3m": 1.0 - crypto[3],
            "pump_prob_6m": 1.0 - crypto[6],
            "pump_prob_9m": 1.0 - crypto[9],
            "pump_prob_12m": 1.0 - crypto[12],
            "ensemble_disagreement_score": round(pstdev([matrix.probabilities[name][1] for name in FORECAST_TYPES]), 6),
            "early_warning_score": matrix.early_warning_score,
            "confidence_score": matrix.confidence_score / 100.0,
            "current_regime": regime_from_systemic_probability(systemic[1]),
        }

    def persist(self, connection: DbConnection, matrix: ProbabilityMatrix, *, target_scope: str = "GLOBAL") -> None:
        row = self.to_row(matrix, target_scope=target_scope)
        columns = tuple(row)
        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(row[column] for column in columns))


def regime_from_systemic_probability(probability: float) -> str:
    if probability >= 0.80:
        return "CRISIS"
    if probability >= 0.60:
        return "HIGH_RISK"
    if probability >= 0.40:
        return "ELEVATED"
    if probability >= 0.20:
        return "WATCH"
    return "LOW_RISK"
