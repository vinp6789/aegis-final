from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Mapping, Protocol, Sequence


DEFAULT_TRADING_PERIODS_PER_YEAR = 252


@dataclass(frozen=True)
class FeeRule:
    asset_class: str
    fee_rate: float
    slippage_rate: float

    @property
    def round_trip_cost(self) -> float:
        return 2.0 * (self.fee_rate + self.slippage_rate)


@dataclass(frozen=True)
class TradeSignal:
    timestamp: datetime
    asset_id: str
    asset_class: str
    gross_return: float
    position: float = 1.0
    forecast_probability: float | None = None
    realized_outcome: int | None = None


@dataclass(frozen=True)
class BacktestObservation:
    timestamp: datetime
    asset_id: str
    asset_class: str
    gross_return: float
    position: float
    fee_cost: float
    slippage_cost: float
    net_return: float
    equity: float


@dataclass(frozen=True)
class PerformanceStats:
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    volatility: float
    win_rate: float
    brier_score: float | None
    total_return: float
    observations: int


@dataclass(frozen=True)
class BacktestResult:
    observations: list[BacktestObservation]
    stats: PerformanceStats
    metadata: dict[str, Any]


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: int
    train_end: int
    test_start: int
    test_end: int


class FeastOfflineStore(Protocol):
    def get_historical_features(self, *, features: Sequence[str], entity_df: Any) -> Any:
        ...


class BacktestEngine:
    def __init__(
        self,
        *,
        fee_rules: Mapping[str, FeeRule] | None = None,
        trading_periods_per_year: int = DEFAULT_TRADING_PERIODS_PER_YEAR,
    ) -> None:
        if trading_periods_per_year <= 0:
            raise ValueError("trading_periods_per_year must be positive")
        self.fee_rules = dict(fee_rules or load_fee_rules())
        self.trading_periods_per_year = trading_periods_per_year

    def run(
        self,
        signals: Sequence[TradeSignal],
        *,
        initial_equity: float = 1.0,
        out_of_sample: bool = True,
    ) -> BacktestResult:
        if initial_equity <= 0.0:
            raise ValueError("initial_equity must be positive")

        equity = initial_equity
        observations: list[BacktestObservation] = []
        for signal in sorted(signals, key=lambda item: item.timestamp):
            rule = self._fee_rule(signal.asset_class)
            exposure = abs(signal.position)
            fee_cost = exposure * rule.fee_rate * 2.0
            slippage_cost = exposure * rule.slippage_rate * 2.0
            net_return = signal.gross_return * signal.position - fee_cost - slippage_cost
            equity *= 1.0 + net_return
            observations.append(
                BacktestObservation(
                    timestamp=signal.timestamp.astimezone(timezone.utc),
                    asset_id=signal.asset_id,
                    asset_class=signal.asset_class,
                    gross_return=signal.gross_return,
                    position=signal.position,
                    fee_cost=round(fee_cost, 10),
                    slippage_cost=round(slippage_cost, 10),
                    net_return=round(net_return, 10),
                    equity=round(equity, 10),
                )
            )

        stats = self.calculate_stats(
            [observation.net_return for observation in observations],
            forecast_probabilities=[
                signal.forecast_probability
                for signal in sorted(signals, key=lambda item: item.timestamp)
                if signal.forecast_probability is not None and signal.realized_outcome is not None
            ],
            realized_outcomes=[
                signal.realized_outcome
                for signal in sorted(signals, key=lambda item: item.timestamp)
                if signal.forecast_probability is not None and signal.realized_outcome is not None
            ],
        )
        return BacktestResult(
            observations=observations,
            stats=stats,
            metadata={
                "initial_equity": initial_equity,
                "final_equity": round(equity, 10),
                "out_of_sample": out_of_sample,
            },
        )

    def calculate_stats(
        self,
        returns: Sequence[float],
        *,
        forecast_probabilities: Sequence[float] | None = None,
        realized_outcomes: Sequence[int] | None = None,
    ) -> PerformanceStats:
        materialized = [float(value) for value in returns]
        observations = len(materialized)
        if observations == 0:
            return PerformanceStats(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None, 0.0, 0)

        total_growth = 1.0
        equity_curve: list[float] = []
        for value in materialized:
            total_growth *= 1.0 + value
            equity_curve.append(total_growth)

        years = observations / self.trading_periods_per_year
        cagr = total_growth ** (1.0 / years) - 1.0 if years > 0.0 and total_growth > 0.0 else 0.0
        average_return = mean(materialized)
        volatility_period = pstdev(materialized) if observations > 1 else 0.0
        volatility = volatility_period * (self.trading_periods_per_year ** 0.5)
        sharpe = (
            average_return / volatility_period * (self.trading_periods_per_year ** 0.5)
            if volatility_period > 0.0
            else 0.0
        )
        downside = [min(0.0, value) for value in materialized]
        downside_deviation = pstdev(downside) if len(downside) > 1 else 0.0
        sortino = (
            average_return / downside_deviation * (self.trading_periods_per_year ** 0.5)
            if downside_deviation > 0.0
            else 0.0
        )
        max_drawdown = self._max_drawdown(equity_curve)
        win_rate = sum(1 for value in materialized if value > 0.0) / observations
        brier_score = self._brier_score(forecast_probabilities, realized_outcomes)

        return PerformanceStats(
            cagr=round(cagr, 10),
            sharpe=round(sharpe, 10),
            sortino=round(sortino, 10),
            max_drawdown=round(max_drawdown, 10),
            volatility=round(volatility, 10),
            win_rate=round(win_rate, 10),
            brier_score=None if brier_score is None else round(brier_score, 10),
            total_return=round(total_growth - 1.0, 10),
            observations=observations,
        )

    def walk_forward_windows(
        self,
        *,
        total_observations: int,
        train_size: int,
        test_size: int,
        step_size: int | None = None,
    ) -> list[WalkForwardWindow]:
        if min(total_observations, train_size, test_size) <= 0:
            raise ValueError("window sizes must be positive")
        step = step_size or test_size
        if step <= 0:
            raise ValueError("step_size must be positive")

        windows: list[WalkForwardWindow] = []
        train_start = 0
        while True:
            train_end = train_start + train_size
            test_start = train_end
            test_end = test_start + test_size
            if test_end > total_observations:
                break
            windows.append(
                WalkForwardWindow(
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
            train_start += step
        return windows

    def evaluate_out_of_sample(
        self,
        signals: Sequence[TradeSignal],
        *,
        train_size: int,
        test_size: int,
    ) -> list[BacktestResult]:
        ordered = sorted(signals, key=lambda item: item.timestamp)
        windows = self.walk_forward_windows(
            total_observations=len(ordered),
            train_size=train_size,
            test_size=test_size,
        )
        return [
            self.run(ordered[window.test_start:window.test_end], out_of_sample=True)
            for window in windows
        ]

    def fetch_feast_offline_features(
        self,
        offline_store: FeastOfflineStore,
        *,
        features: Sequence[str],
        entity_df: Any,
    ) -> Any:
        return offline_store.get_historical_features(features=features, entity_df=entity_df)

    def _fee_rule(self, asset_class: str) -> FeeRule:
        key = normalize_asset_class(asset_class)
        if key not in self.fee_rules:
            raise ValueError(f"No fee rule configured for asset class: {asset_class}")
        return self.fee_rules[key]

    @staticmethod
    def _max_drawdown(equity_curve: Sequence[float]) -> float:
        peak = 0.0
        max_drawdown = 0.0
        for equity in equity_curve:
            peak = max(peak, equity)
            if peak > 0.0:
                max_drawdown = min(max_drawdown, equity / peak - 1.0)
        return max_drawdown

    @staticmethod
    def _brier_score(
        forecast_probabilities: Sequence[float] | None,
        realized_outcomes: Sequence[int] | None,
    ) -> float | None:
        if not forecast_probabilities or not realized_outcomes:
            return None
        length = min(len(forecast_probabilities), len(realized_outcomes))
        if length == 0:
            return None
        return mean(
            (max(0.0, min(1.0, float(forecast_probabilities[index]))) - int(realized_outcomes[index])) ** 2
            for index in range(length)
        )


def load_fee_rules(config_path: Path | None = None) -> dict[str, FeeRule]:
    path = config_path or Path(__file__).resolve().parents[2] / "config" / "fees_config.yaml"
    parsed = _parse_fee_yaml(path.read_text(encoding="utf-8"))
    rules: dict[str, FeeRule] = {}
    for asset_class, values in parsed.items():
        rules[normalize_asset_class(asset_class)] = FeeRule(
            asset_class=normalize_asset_class(asset_class),
            fee_rate=float(values["fee_rate"]),
            slippage_rate=float(values["slippage_rate"]),
        )
    return rules


def normalize_asset_class(asset_class: str) -> str:
    return asset_class.strip().lower().replace(" ", "_").replace("-", "_")


def _parse_fee_yaml(raw: str) -> dict[str, dict[str, float]]:
    rules: dict[str, dict[str, float]] = {}
    current: str | None = None
    in_asset_classes = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "asset_classes:":
            in_asset_classes = True
            continue
        if not in_asset_classes:
            continue
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            current = normalize_asset_class(stripped[:-1])
            rules[current] = {}
            continue
        if current is not None and line.startswith("    ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            if key in {"fee_rate", "slippage_rate"}:
                rules[current][key] = float(value.strip())
    return rules
