from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Mapping, Sequence

from analytics.common import clamp, normalize_timestamp


INDIA_SECTORS = (
    "BANKING",
    "NBFC",
    "REALTY",
    "AUTO",
    "IT",
    "PHARMA",
    "ENERGY",
    "CAPITAL_GOODS",
    "PSU",
    "FMCG",
    "METALS",
    "INFRASTRUCTURE",
    "CHEMICALS",
    "CONSUMPTION",
    "DEFENSE",
    "RAILWAYS",
)

ROLLING_WINDOWS = (30, 90, 180, 360)


@dataclass(frozen=True)
class SectorInput:
    timestamp: datetime
    sector: str
    close: float | None = None
    previous_close: float | None = None
    market_cap: float | None = None
    sector_weight: float | None = None
    fii_flow: float | None = None
    dii_flow: float | None = None
    liquidity_index: float | None = None
    leading_diffusion_index: float | None = None
    regime_probability: float | None = None
    volatility_index: float | None = None
    earnings_revision: float | None = None


@dataclass(frozen=True)
class SectorMetrics:
    timestamp: datetime
    sector: str
    sector_health_score: float
    stress_score: float
    expansion_score: float
    rotation_score: float
    expected_drawdown: float
    expected_upside: float
    crash_probability: float
    early_warning_score: float
    sector_similarity_score: float
    sector_novelty_score: float


@dataclass(frozen=True)
class SectorOutcome:
    sector: str
    window_days: int
    realized_return: float
    max_drawdown: float
    max_upside: float
    observations: int


class IndiaSectorIntelligenceEngine:
    def __init__(self, *, sectors: Sequence[str] = INDIA_SECTORS) -> None:
        normalized = tuple(normalize_sector(sector) for sector in sectors)
        missing = set(INDIA_SECTORS) - set(normalized)
        if missing:
            raise ValueError(f"Missing required India sectors: {sorted(missing)}")
        self.sectors = normalized

    def score_sector(
        self,
        sector_input: SectorInput,
        *,
        historical_metrics: Sequence[SectorMetrics] | None = None,
    ) -> SectorMetrics:
        sector = normalize_sector(sector_input.sector)
        if sector not in self.sectors:
            raise ValueError(f"Unsupported sector: {sector_input.sector}")
        momentum = sector_momentum(sector_input)
        flow_score = normalized_flow_score(sector_input.fii_flow, sector_input.dii_flow)
        liquidity = clean_index(sector_input.liquidity_index, 50.0)
        breadth = (clean_ldi(sector_input.leading_diffusion_index) + 1.0) / 2.0 * 100.0
        regime_stability = (1.0 - clean_probability(sector_input.regime_probability, 0.5)) * 100.0
        volatility_resilience = 100.0 - clean_index(sector_input.volatility_index, 30.0)
        earnings = normalized_signed_score(sector_input.earnings_revision)

        health = weighted_score(
            (liquidity, 0.20),
            (breadth, 0.20),
            (momentum, 0.18),
            (flow_score, 0.16),
            (regime_stability, 0.14),
            (volatility_resilience, 0.07),
            (earnings, 0.05),
        )
        stress = weighted_score(
            (100.0 - health, 0.45),
            (clean_index(sector_input.volatility_index, 30.0), 0.25),
            (100.0 - liquidity, 0.15),
            (clean_probability(sector_input.regime_probability, 0.5) * 100.0, 0.15),
        )
        expansion = weighted_score(
            (health, 0.45),
            (momentum, 0.25),
            (earnings, 0.15),
            (liquidity, 0.15),
        )
        rotation = weighted_score(
            (momentum, 0.35),
            (flow_score, 0.30),
            (100.0 - clean_index(sector_input.volatility_index, 30.0), 0.15),
            (clean_weight(sector_input.sector_weight), 0.20),
        )
        expected_drawdown = clamp((stress / 100.0) * 0.35 + max(0.0, 50.0 - momentum) / 100.0 * 0.20, 0.0, 1.0)
        expected_upside = clamp((expansion / 100.0) * 0.30 + max(0.0, momentum - 50.0) / 100.0 * 0.25, 0.0, 1.0)
        crash_probability = clamp((stress * 0.70 + (100.0 - health) * 0.30) / 100.0, 0.0, 1.0)
        early_warning = weighted_score(
            (stress, 0.45),
            (crash_probability * 100.0, 0.25),
            (100.0 - liquidity, 0.15),
            (clean_index(sector_input.volatility_index, 30.0), 0.15),
        )
        similarity = sector_similarity_score(
            provisional_vector(
                health=health,
                stress=stress,
                expansion=expansion,
                rotation=rotation,
                crash_probability=crash_probability,
            ),
            historical_metrics or (),
        )
        novelty = 100.0 - similarity if historical_metrics else 0.0
        return SectorMetrics(
            timestamp=normalize_timestamp(sector_input.timestamp),
            sector=sector,
            sector_health_score=round(clamp(health, 0.0, 100.0), 6),
            stress_score=round(clamp(stress, 0.0, 100.0), 6),
            expansion_score=round(clamp(expansion, 0.0, 100.0), 6),
            rotation_score=round(clamp(rotation, 0.0, 100.0), 6),
            expected_drawdown=round(clamp(expected_drawdown, 0.0, 1.0), 6),
            expected_upside=round(clamp(expected_upside, 0.0, 1.0), 6),
            crash_probability=round(clamp(crash_probability, 0.0, 1.0), 6),
            early_warning_score=round(clamp(early_warning, 0.0, 100.0), 6),
            sector_similarity_score=round(clamp(similarity, 0.0, 100.0), 6),
            sector_novelty_score=round(clamp(novelty, 0.0, 100.0), 6),
        )

    def score_all(self, sector_inputs: Sequence[SectorInput]) -> dict[str, SectorMetrics]:
        latest_by_sector: dict[str, SectorInput] = {}
        for item in sector_inputs:
            sector = normalize_sector(item.sector)
            existing = latest_by_sector.get(sector)
            if existing is None or normalize_timestamp(item.timestamp) >= normalize_timestamp(existing.timestamp):
                latest_by_sector[sector] = item
        return {
            sector: self.score_sector(latest_by_sector.get(sector) or default_input(sector))
            for sector in self.sectors
        }

    def rolling_outcomes(
        self,
        history: Sequence[SectorInput],
        *,
        windows: Sequence[int] = ROLLING_WINDOWS,
    ) -> dict[str, dict[int, SectorOutcome]]:
        grouped: dict[str, list[SectorInput]] = {sector: [] for sector in self.sectors}
        for item in history:
            sector = normalize_sector(item.sector)
            if sector in grouped:
                grouped[sector].append(item)
        outcomes: dict[str, dict[int, SectorOutcome]] = {}
        for sector in self.sectors:
            sector_history = sorted(grouped[sector], key=lambda item: normalize_timestamp(item.timestamp))
            outcomes[sector] = {
                int(window): rolling_outcome(sector, sector_history, int(window))
                for window in windows
            }
        return outcomes


def from_feast_rows(rows: Sequence[Mapping[str, Any]]) -> list[SectorInput]:
    inputs: list[SectorInput] = []
    for row in rows:
        inputs.append(
            SectorInput(
                timestamp=normalize_timestamp(row.get("timestamp") or row.get("event_timestamp")),
                sector=str(row.get("sector", row.get("sector_name", "BANKING"))),
                close=row.get("close"),
                previous_close=row.get("previous_close"),
                market_cap=row.get("market_cap"),
                sector_weight=row.get("sector_weight"),
                fii_flow=row.get("fii_flow"),
                dii_flow=row.get("dii_flow"),
                liquidity_index=row.get("liquidity_index"),
                leading_diffusion_index=row.get("leading_diffusion_index"),
                regime_probability=row.get("regime_probability"),
                volatility_index=row.get("volatility_index"),
                earnings_revision=row.get("earnings_revision"),
            )
        )
    return inputs


def rolling_outcome(sector: str, history: Sequence[SectorInput], window_days: int) -> SectorOutcome:
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if not history:
        return SectorOutcome(sector=sector, window_days=window_days, realized_return=0.0, max_drawdown=0.0, max_upside=0.0, observations=0)
    window = list(history[-window_days:])
    prices = [clean_positive(item.close, 0.0) for item in window if clean_positive(item.close, 0.0) > 0.0]
    if len(prices) < 2:
        return SectorOutcome(sector=sector, window_days=window_days, realized_return=0.0, max_drawdown=0.0, max_upside=0.0, observations=len(prices))
    start = prices[0]
    realized = (prices[-1] - start) / start if start else 0.0
    peak = prices[0]
    trough = prices[0]
    max_drawdown = 0.0
    max_upside = 0.0
    for price in prices:
        peak = max(peak, price)
        trough = min(trough, price)
        if peak > 0.0:
            max_drawdown = min(max_drawdown, (price - peak) / peak)
        if trough > 0.0:
            max_upside = max(max_upside, (price - trough) / trough)
    return SectorOutcome(
        sector=sector,
        window_days=window_days,
        realized_return=round(clamp(realized, -1.0, 10.0), 6),
        max_drawdown=round(clamp(max_drawdown, -1.0, 0.0), 6),
        max_upside=round(clamp(max_upside, 0.0, 10.0), 6),
        observations=len(prices),
    )


def sector_similarity_score(current_vector: Sequence[float], historical_metrics: Sequence[SectorMetrics]) -> float:
    if not historical_metrics:
        return 0.0
    similarities = [
        cosine_similarity(current_vector, metrics_vector(metric))
        for metric in historical_metrics
    ]
    return clamp(max(similarities) * 100.0, 0.0, 100.0)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    length = min(len(left), len(right))
    if length == 0:
        return 0.0
    a = [float(left[index]) for index in range(length)]
    b = [float(right[index]) for index in range(length)]
    numerator = sum(x * y for x, y in zip(a, b))
    left_norm = math.sqrt(sum(x * x for x in a))
    right_norm = math.sqrt(sum(y * y for y in b))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return clamp(numerator / (left_norm * right_norm), 0.0, 1.0)


def metrics_vector(metric: SectorMetrics) -> list[float]:
    return provisional_vector(
        health=metric.sector_health_score,
        stress=metric.stress_score,
        expansion=metric.expansion_score,
        rotation=metric.rotation_score,
        crash_probability=metric.crash_probability,
    )


def provisional_vector(
    *,
    health: float,
    stress: float,
    expansion: float,
    rotation: float,
    crash_probability: float,
) -> list[float]:
    return [
        clamp(health, 0.0, 100.0) / 100.0,
        clamp(stress, 0.0, 100.0) / 100.0,
        clamp(expansion, 0.0, 100.0) / 100.0,
        clamp(rotation, 0.0, 100.0) / 100.0,
        clamp(crash_probability, 0.0, 1.0),
    ]


def sector_momentum(sector_input: SectorInput) -> float:
    close = clean_positive(sector_input.close, 100.0)
    previous = clean_positive(sector_input.previous_close, close)
    if previous <= 0.0:
        return 50.0
    change = (close - previous) / previous
    return clamp(50.0 + change * 500.0, 0.0, 100.0)


def normalized_flow_score(fii_flow: float | None, dii_flow: float | None) -> float:
    flow = clean_number(fii_flow, 0.0) + clean_number(dii_flow, 0.0)
    return clamp(50.0 + math.tanh(flow / 1000.0) * 50.0, 0.0, 100.0)


def normalized_signed_score(value: float | None) -> float:
    return clamp(50.0 + math.tanh(clean_number(value, 0.0)) * 50.0, 0.0, 100.0)


def weighted_score(*components: tuple[float, float]) -> float:
    total_weight = sum(weight for _value, weight in components)
    if total_weight <= 0.0:
        return 0.0
    return clamp(sum(clamp(value, 0.0, 100.0) * weight for value, weight in components) / total_weight, 0.0, 100.0)


def default_input(sector: str) -> SectorInput:
    return SectorInput(timestamp=datetime.now(timezone.utc), sector=sector)


def normalize_sector(sector: str) -> str:
    return sector.upper().replace(" ", "_").replace("&", "AND")


def clean_number(value: float | int | None, default: float) -> float:
    if value is None:
        return default
    parsed = float(value)
    if math.isnan(parsed):
        return default
    return parsed


def clean_positive(value: float | int | None, default: float) -> float:
    return max(0.0, clean_number(value, default))


def clean_index(value: float | int | None, default: float) -> float:
    return clamp(clean_number(value, default), 0.0, 100.0)


def clean_probability(value: float | int | None, default: float) -> float:
    return clamp(clean_number(value, default), 0.0, 1.0)


def clean_ldi(value: float | int | None) -> float:
    return clamp(clean_number(value, 0.0), -1.0, 1.0)


def clean_weight(value: float | int | None) -> float:
    return clamp(clean_number(value, 0.05) * 100.0, 0.0, 100.0)
