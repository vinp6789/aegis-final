from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from analytics.common import clamp, clip_probability, normalize_timestamp


REGIME_STATES = ("RISK_ON", "NEUTRAL", "RISK_OFF", "CRISIS")


@dataclass(frozen=True)
class RegimeMemoryConfig:
    rolling_dtw_window_days: int = 63
    decay_factor: float = 0.97
    top_k: int = 3
    liquidity_weight: float = 0.25
    breadth_weight: float = 0.25
    regime_state_weight: float = 0.20
    probability_vector_weight: float = 0.30


@dataclass(frozen=True)
class RegimeFeatureVector:
    timestamp: datetime
    liquidity: Sequence[float | int | None]
    breadth: Sequence[float | int | None]
    regime_state: str
    probability_vector: Sequence[float | int | None]


@dataclass(frozen=True)
class AnalogOutcome:
    future_drawdown: float
    future_volatility: float
    liquidity_deterioration: float
    sector_stress_outcome: float


@dataclass(frozen=True)
class HistoricalAnalog:
    analog_id: str
    features: RegimeFeatureVector
    outcome: AnalogOutcome


@dataclass(frozen=True)
class AnalogMatch:
    analog_id: str
    timestamp: datetime
    similarity_index: float
    cosine_similarity: float
    dtw_distance: float
    decay_weight: float
    regime_state_match: bool
    outcome: AnalogOutcome


class HistoricalStore(Protocol):
    def fetch_regime_history(self, *, start: datetime | None = None, end: datetime | None = None) -> Sequence[Mapping[str, Any]]:
        ...


class RegimeMemoryEngine:
    def __init__(self, config: RegimeMemoryConfig | None = None) -> None:
        self.config = config or load_regime_config()

    def find_top_analogs(
        self,
        current: RegimeFeatureVector,
        history: Sequence[HistoricalAnalog],
    ) -> list[AnalogMatch]:
        matches = [self.score_analog(current, analog) for analog in history]
        matches.sort(key=lambda item: item.similarity_index, reverse=True)
        return matches[: self.config.top_k]

    def score_analog(self, current: RegimeFeatureVector, analog: HistoricalAnalog) -> AnalogMatch:
        liquidity_current = clean_series(current.liquidity)
        liquidity_hist = clean_series(analog.features.liquidity)
        breadth_current = clean_series(current.breadth)
        breadth_hist = clean_series(analog.features.breadth)
        prob_current = [clip_probability(value) for value in current.probability_vector]
        prob_hist = [clip_probability(value) for value in analog.features.probability_vector]

        liquidity_similarity = dtw_similarity(liquidity_current, liquidity_hist)
        breadth_similarity = cosine_to_unit(cosine_similarity(breadth_current, breadth_hist))
        probability_similarity = cosine_to_unit(cosine_similarity(prob_current, prob_hist))
        regime_match = normalize_regime(current.regime_state) == normalize_regime(analog.features.regime_state)
        regime_similarity = 1.0 if regime_match else 0.0
        decay = time_decay_weight(
            current.timestamp,
            analog.features.timestamp,
            self.config.decay_factor,
            self.config.rolling_dtw_window_days,
        )
        weighted_similarity = (
            liquidity_similarity * self.config.liquidity_weight
            + breadth_similarity * self.config.breadth_weight
            + regime_similarity * self.config.regime_state_weight
            + probability_similarity * self.config.probability_vector_weight
        )
        similarity_index = clamp(weighted_similarity * decay * 100.0, 0.0, 100.0)

        return AnalogMatch(
            analog_id=analog.analog_id,
            timestamp=normalize_timestamp(analog.features.timestamp),
            similarity_index=round(similarity_index, 6),
            cosine_similarity=round(probability_similarity, 6),
            dtw_distance=round(dynamic_time_warping(liquidity_current, liquidity_hist), 6),
            decay_weight=round(decay, 6),
            regime_state_match=regime_match,
            outcome=analog.outcome,
        )

    def retrieve_historical_analogs(
        self,
        store: HistoricalStore,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[HistoricalAnalog]:
        return [analog_from_row(row) for row in store.fetch_regime_history(start=start, end=end)]

    def dtw_output_matrix(self, current: RegimeFeatureVector, history: Sequence[HistoricalAnalog]) -> list[list[float]]:
        current_series = clean_series(current.liquidity)
        return [dtw_matrix(current_series, clean_series(analog.features.liquidity))[-1] for analog in history]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    a, b = same_length(clean_series(left), clean_series(right))
    numerator = sum(x * y for x, y in zip(a, b))
    left_norm = math.sqrt(sum(x * x for x in a))
    right_norm = math.sqrt(sum(y * y for y in b))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return clamp(numerator / (left_norm * right_norm), -1.0, 1.0)


def dynamic_time_warping(left: Sequence[float], right: Sequence[float]) -> float:
    matrix = dtw_matrix(left, right)
    return matrix[-1][-1]


def dtw_matrix(left: Sequence[float], right: Sequence[float]) -> list[list[float]]:
    a = clean_series(left)
    b = clean_series(right)
    rows = len(a) + 1
    cols = len(b) + 1
    matrix = [[math.inf for _col in range(cols)] for _row in range(rows)]
    matrix[0][0] = 0.0
    for row in range(1, rows):
        for col in range(1, cols):
            cost = abs(a[row - 1] - b[col - 1])
            matrix[row][col] = cost + min(
                matrix[row - 1][col],
                matrix[row][col - 1],
                matrix[row - 1][col - 1],
            )
    return [line[1:] for line in matrix[1:]]


def dtw_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    distance = dynamic_time_warping(left, right)
    scale = max(len(left), len(right), 1)
    return clamp(1.0 / (1.0 + distance / scale), 0.0, 1.0)


def time_decay_weight(current_time: datetime, analog_time: datetime, decay_factor: float, window_days: int) -> float:
    days = max(0, (normalize_timestamp(current_time) - normalize_timestamp(analog_time)).days)
    windows_elapsed = days / max(window_days, 1)
    return clamp(decay_factor ** windows_elapsed, 0.0, 1.0)


def analog_from_row(row: Mapping[str, Any]) -> HistoricalAnalog:
    return HistoricalAnalog(
        analog_id=str(row.get("analog_id", row.get("id", ""))),
        features=RegimeFeatureVector(
            timestamp=normalize_timestamp(row.get("timestamp")),
            liquidity=row.get("liquidity", []),
            breadth=row.get("breadth", []),
            regime_state=str(row.get("regime_state", "NEUTRAL")),
            probability_vector=row.get("probability_vector", []),
        ),
        outcome=AnalogOutcome(
            future_drawdown=float(row.get("future_drawdown", 0.0) or 0.0),
            future_volatility=float(row.get("future_volatility", 0.0) or 0.0),
            liquidity_deterioration=float(row.get("liquidity_deterioration", 0.0) or 0.0),
            sector_stress_outcome=float(row.get("sector_stress_outcome", 0.0) or 0.0),
        ),
    )


def load_regime_config(config_path: Path | None = None) -> RegimeMemoryConfig:
    path = config_path or Path(__file__).resolve().parents[2] / "config" / "regime_config.yaml"
    data = parse_simple_yaml(path.read_text(encoding="utf-8"))
    search = data.get("search", {})
    weights = data.get("weights", {})
    return RegimeMemoryConfig(
        rolling_dtw_window_days=int(search.get("rolling_dtw_window_days", 63)),
        decay_factor=float(search.get("decay_factor", 0.97)),
        top_k=int(search.get("top_k", 3)),
        liquidity_weight=float(weights.get("liquidity", 0.25)),
        breadth_weight=float(weights.get("breadth", 0.25)),
        regime_state_weight=float(weights.get("regime_state", 0.20)),
        probability_vector_weight=float(weights.get("probability_vectors", 0.30)),
    )


def parse_simple_yaml(raw: str) -> dict[str, dict[str, float | int]]:
    parsed: dict[str, dict[str, float | int]] = {}
    current: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.endswith(":"):
            current = stripped[:-1]
            parsed[current] = {}
            continue
        if current and ":" in stripped:
            key, value = stripped.split(":", 1)
            parsed[current][key] = parse_scalar(value.strip())
    return parsed


def parse_scalar(value: str) -> float | int:
    number = float(value)
    return int(number) if number.is_integer() else number


def clean_series(values: Sequence[float | int | None]) -> list[float]:
    return [0.0 if value is None else float(value) for value in values]


def same_length(left: Sequence[float], right: Sequence[float]) -> tuple[list[float], list[float]]:
    length = min(len(left), len(right))
    if length == 0:
        return [0.0], [0.0]
    return list(left[-length:]), list(right[-length:])


def cosine_to_unit(value: float) -> float:
    return clamp((value + 1.0) / 2.0, 0.0, 1.0)


def normalize_regime(value: str) -> str:
    normalized = value.strip().upper()
    return normalized if normalized in REGIME_STATES else "NEUTRAL"
