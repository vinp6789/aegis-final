from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

from analytics.common import clamp, normalize_timestamp


@dataclass(frozen=True)
class ComponentSnapshot:
    timestamp: datetime
    ticker: str
    close_price: float | None
    previous_close: float | None
    sma_50: float | None
    sma_200: float | None
    market_cap: float | None
    new_high: bool = False
    new_low: bool = False


@dataclass(frozen=True)
class BreadthMetrics:
    timestamp: datetime
    leading_diffusion_index: float
    advance_decline_ratio: float
    new_high_new_low_ratio: float
    percent_above_50_sma: float
    percent_above_200_sma: float
    equal_weight_vs_cap_weight_spread: float
    hhi_concentration_score: float
    advance_decline_line: float


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


class BreadthEngine:
    table_name = "breadth_metrics"

    def calculate_daily_metrics(
        self,
        components: Sequence[ComponentSnapshot],
        *,
        previous_advance_decline_line: float = 0.0,
    ) -> BreadthMetrics:
        if not components:
            raise ValueError("components must not be empty")
        timestamp = max(component.timestamp for component in components).astimezone(timezone.utc)
        valid_prices = [
            component
            for component in components
            if component.close_price is not None and component.previous_close is not None
        ]
        total = max(len(valid_prices), 1)
        advances = sum(1 for component in valid_prices if component.close_price > component.previous_close)
        declines = sum(1 for component in valid_prices if component.close_price < component.previous_close)
        unchanged = total - advances - declines
        advance_decline_ratio = advances / max(declines, 1)
        advance_decline_line = previous_advance_decline_line + advances - declines

        above_50 = ratio(
            component.close_price is not None
            and component.sma_50 is not None
            and component.close_price > component.sma_50
            for component in components
        )
        above_200 = ratio(
            component.close_price is not None
            and component.sma_200 is not None
            and component.close_price > component.sma_200
            for component in components
        )
        new_highs = sum(1 for component in components if component.new_high)
        new_lows = sum(1 for component in components if component.new_low)
        high_low_ratio = new_highs / max(new_highs + new_lows, 1)
        equal_weight_return = mean_safe(
            [
                (component.close_price - component.previous_close) / component.previous_close
                for component in valid_prices
                if component.previous_close and component.previous_close != 0.0
            ]
        )
        cap_weight_return = self.cap_weight_return(valid_prices)
        spread = equal_weight_return - cap_weight_return
        hhi = self.hhi_concentration_score(components)
        concentration_penalty = hhi * 0.25

        diffusion = (
            ((advances - declines) / max(advances + declines + unchanged, 1)) * 0.30
            + (above_50 * 2.0 - 1.0) * 0.25
            + (above_200 * 2.0 - 1.0) * 0.20
            + (high_low_ratio * 2.0 - 1.0) * 0.15
            + clamp(spread * 10.0, -1.0, 1.0) * 0.10
            - concentration_penalty
        )

        return BreadthMetrics(
            timestamp=timestamp,
            leading_diffusion_index=round(clamp(diffusion, -1.0, 1.0), 6),
            advance_decline_ratio=round(advance_decline_ratio, 6),
            new_high_new_low_ratio=round(high_low_ratio, 6),
            percent_above_50_sma=round(above_50, 6),
            percent_above_200_sma=round(above_200, 6),
            equal_weight_vs_cap_weight_spread=round(spread, 6),
            hhi_concentration_score=round(hhi, 6),
            advance_decline_line=round(advance_decline_line, 6),
        )

    def calculate_history(
        self,
        historical_components: Sequence[Sequence[ComponentSnapshot]],
    ) -> list[BreadthMetrics]:
        outputs: list[BreadthMetrics] = []
        ad_line = 0.0
        for components in historical_components:
            metrics = self.calculate_daily_metrics(
                components,
                previous_advance_decline_line=ad_line,
            )
            ad_line = metrics.advance_decline_line
            outputs.append(metrics)
        return outputs

    def hhi_concentration_score(self, components: Sequence[ComponentSnapshot]) -> float:
        caps = [max(0.0, float(component.market_cap or 0.0)) for component in components]
        total_cap = sum(caps)
        if total_cap <= 0.0:
            return 0.0
        return clamp(sum((cap / total_cap) ** 2 for cap in caps), 0.0, 1.0)

    def cap_weight_return(self, components: Sequence[ComponentSnapshot]) -> float:
        weighted_returns: list[float] = []
        weights: list[float] = []
        for component in components:
            if not component.previous_close or component.previous_close == 0.0:
                continue
            cap = max(0.0, float(component.market_cap or 0.0))
            if cap <= 0.0:
                continue
            weights.append(cap)
            weighted_returns.append((component.close_price - component.previous_close) / component.previous_close)
        total_weight = sum(weights)
        if total_weight <= 0.0:
            return 0.0
        return sum(value * weight / total_weight for value, weight in zip(weighted_returns, weights))

    def persist_metrics(self, connection: DbConnection, metrics: Sequence[BreadthMetrics]) -> None:
        if not metrics:
            return
        rows = [self.to_row(metric) for metric in metrics]
        columns = tuple(rows[0])
        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        with connection.cursor() as cursor:
            for row in rows:
                cursor.execute(sql, tuple(row[column] for column in columns))

    def to_row(self, metric: BreadthMetrics) -> dict[str, Any]:
        return {
            "timestamp": metric.timestamp,
            "leading_diffusion_index": metric.leading_diffusion_index,
            "advance_decline_ratio": metric.advance_decline_ratio,
            "new_high_new_low_ratio": metric.new_high_new_low_ratio,
            "percent_above_50_sma": metric.percent_above_50_sma,
            "percent_above_200_sma": metric.percent_above_200_sma,
            "equal_weight_vs_cap_weight_spread": metric.equal_weight_vs_cap_weight_spread,
            "hhi_concentration_score": metric.hhi_concentration_score,
            "advance_decline_line": metric.advance_decline_line,
        }

    def from_feature_rows(self, rows: Sequence[Mapping[str, Any]]) -> list[ComponentSnapshot]:
        return [
            ComponentSnapshot(
                timestamp=parse_timestamp(row.get("timestamp")),
                ticker=str(row.get("ticker", row.get("asset_id", ""))),
                close_price=clean_optional(row.get("close_price", row.get("close"))),
                previous_close=clean_optional(row.get("previous_close")),
                sma_50=clean_optional(row.get("sma_50")),
                sma_200=clean_optional(row.get("sma_200")),
                market_cap=clean_optional(row.get("market_cap")),
                new_high=bool(row.get("new_high", False)),
                new_low=bool(row.get("new_low", False)),
            )
            for row in rows
        ]


def ratio(flags: Sequence[bool] | Any) -> float:
    values = list(flags)
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def mean_safe(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def clean_optional(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def parse_timestamp(value: Any) -> datetime:
    return normalize_timestamp(value)
