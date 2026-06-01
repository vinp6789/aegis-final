from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Mapping, Sequence

from analytics.common import clamp, normalize_timestamp


CRYPTO_NARRATIVES = (
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "L1",
    "L2",
    "AI",
    "RWA",
    "DEFI",
    "DEPIN",
    "GAMING",
    "MEMES",
)

TRANSITION_STATES = ("ACCUMULATION", "EXPANSION", "DISTRIBUTION", "STRESS")


@dataclass(frozen=True)
class CryptoNarrativeInput:
    timestamp: datetime
    narrative: str
    market_cap: float | None = None
    previous_market_cap: float | None = None
    volume: float | None = None
    previous_volume: float | None = None
    coinbase_price: float | None = None
    global_spot_price: float | None = None
    etf_inflow: float | None = None
    exchange_inflow: float | None = None
    funding_rate: float | None = None
    open_interest: float | None = None
    previous_open_interest: float | None = None
    stablecoin_supply: float | None = None
    previous_stablecoin_supply: float | None = None
    buy_volume: float | None = None
    sell_volume: float | None = None


@dataclass(frozen=True)
class CryptoNarrativeMetrics:
    timestamp: datetime
    narrative: str
    narrative_health: float
    stress_score: float
    rotation_score: float
    crash_probability: float
    pump_probability: float
    expected_drawdown: float
    expected_upside: float
    early_warning_score: float
    stablecoin_growth_rate: float
    stablecoin_velocity: float
    coinbase_premium: float
    cumulative_volume_delta: float
    funding_stress: float
    open_interest_growth: float
    narrative_similarity_score: float


class CryptoIntelligenceEngine:
    def __init__(self, *, narratives: Sequence[str] = CRYPTO_NARRATIVES) -> None:
        normalized = tuple(normalize_narrative(item) for item in narratives)
        missing = set(CRYPTO_NARRATIVES) - set(normalized)
        if missing:
            raise ValueError(f"Missing required crypto narratives: {sorted(missing)}")
        self.narratives = normalized

    def score_narrative(
        self,
        narrative_input: CryptoNarrativeInput,
        *,
        historical_metrics: Sequence[CryptoNarrativeMetrics] | None = None,
    ) -> CryptoNarrativeMetrics:
        narrative = normalize_narrative(narrative_input.narrative)
        if narrative not in self.narratives:
            raise ValueError(f"Unsupported crypto narrative: {narrative_input.narrative}")
        momentum = market_cap_momentum(narrative_input)
        liquidity = volume_liquidity_score(narrative_input.volume, narrative_input.previous_volume)
        premium = coinbase_premium(narrative_input.coinbase_price, narrative_input.global_spot_price)
        premium_score = normalized_signed_score(premium * 20.0)
        stable_growth = stablecoin_growth_rate(
            narrative_input.stablecoin_supply,
            narrative_input.previous_stablecoin_supply,
        )
        stable_score = normalized_signed_score(stable_growth * 5.0)
        cvd = cumulative_volume_delta(narrative_input.buy_volume, narrative_input.sell_volume)
        cvd_score = normalized_signed_score(cvd / max(clean_positive(narrative_input.volume, 1.0), 1.0) * 10.0)
        etf_score = normalized_signed_score(clean_number(narrative_input.etf_inflow, 0.0) / 1000.0)
        exchange_pressure = normalized_signed_score(-clean_number(narrative_input.exchange_inflow, 0.0) / 1000.0)
        funding = funding_stress_score(narrative_input.funding_rate)
        oi_growth = open_interest_growth(narrative_input.open_interest, narrative_input.previous_open_interest)
        oi_stress = normalized_signed_score(abs(oi_growth) * 4.0) if funding > 60.0 else normalized_signed_score(oi_growth * 2.0)

        health = weighted_score(
            (momentum, 0.22),
            (liquidity, 0.15),
            (premium_score, 0.12),
            (stable_score, 0.14),
            (cvd_score, 0.13),
            (etf_score, 0.10),
            (exchange_pressure, 0.08),
            (100.0 - funding, 0.06),
        )
        stress = weighted_score(
            (100.0 - health, 0.35),
            (funding, 0.20),
            (100.0 - stable_score, 0.15),
            (100.0 - cvd_score, 0.15),
            (100.0 - exchange_pressure, 0.15),
        )
        rotation = weighted_score(
            (momentum, 0.30),
            (liquidity, 0.20),
            (premium_score, 0.15),
            (etf_score, 0.15),
            (oi_stress, 0.20),
        )
        crash = clamp((stress * 0.70 + (100.0 - stable_score) * 0.20 + funding * 0.10) / 100.0, 0.0, 1.0)
        pump = clamp((health * 0.50 + rotation * 0.30 + stable_score * 0.20) / 100.0, 0.0, 1.0)
        drawdown = clamp(crash * 0.45 + max(0.0, 50.0 - momentum) / 100.0 * 0.20, 0.0, 1.0)
        upside = clamp(pump * 0.55 + max(0.0, momentum - 50.0) / 100.0 * 0.25, 0.0, 1.0)
        early_warning = weighted_score((stress, 0.50), (crash * 100.0, 0.30), (funding, 0.20))
        similarity = narrative_similarity_score(
            provisional_vector(health, stress, rotation, crash, pump),
            historical_metrics or (),
        )
        return CryptoNarrativeMetrics(
            timestamp=normalize_timestamp(narrative_input.timestamp),
            narrative=narrative,
            narrative_health=round(health, 6),
            stress_score=round(stress, 6),
            rotation_score=round(rotation, 6),
            crash_probability=round(crash, 6),
            pump_probability=round(pump, 6),
            expected_drawdown=round(drawdown, 6),
            expected_upside=round(upside, 6),
            early_warning_score=round(early_warning, 6),
            stablecoin_growth_rate=round(clamp(stable_growth, -1.0, 10.0), 6),
            stablecoin_velocity=round(stablecoin_velocity(narrative_input.volume, narrative_input.stablecoin_supply), 6),
            coinbase_premium=round(clamp(premium, -1.0, 1.0), 6),
            cumulative_volume_delta=round(cvd, 6),
            funding_stress=round(funding, 6),
            open_interest_growth=round(clamp(oi_growth, -1.0, 10.0), 6),
            narrative_similarity_score=round(similarity, 6),
        )

    def score_all(self, inputs: Sequence[CryptoNarrativeInput]) -> dict[str, CryptoNarrativeMetrics]:
        latest_by_narrative: dict[str, CryptoNarrativeInput] = {}
        for item in inputs:
            narrative = normalize_narrative(item.narrative)
            existing = latest_by_narrative.get(narrative)
            if existing is None or normalize_timestamp(item.timestamp) >= normalize_timestamp(existing.timestamp):
                latest_by_narrative[narrative] = item
        return {
            narrative: self.score_narrative(latest_by_narrative.get(narrative) or default_input(narrative))
            for narrative in self.narratives
        }

    def transition_matrix(self, metrics: Sequence[CryptoNarrativeMetrics]) -> dict[str, dict[str, float]]:
        if not metrics:
            return {state: uniform_row() for state in TRANSITION_STATES}
        avg_stress = mean(metric.stress_score for metric in metrics) / 100.0
        avg_pump = mean(metric.pump_probability for metric in metrics)
        raw = {
            "ACCUMULATION": max(0.01, 0.30 + (1.0 - avg_stress) * 0.25),
            "EXPANSION": max(0.01, 0.25 + avg_pump * 0.30),
            "DISTRIBUTION": max(0.01, 0.20 + abs(avg_pump - avg_stress) * 0.20),
            "STRESS": max(0.01, 0.20 + avg_stress * 0.45),
        }
        total = sum(raw.values())
        row = {state: round(value / total, 10) for state, value in raw.items()}
        return {state: dict(row) for state in TRANSITION_STATES}


def from_market_rows(rows: Sequence[Mapping[str, Any]]) -> list[CryptoNarrativeInput]:
    inputs: list[CryptoNarrativeInput] = []
    for row in rows:
        inputs.append(
            CryptoNarrativeInput(
                timestamp=normalize_timestamp(row.get("timestamp") or row.get("event_timestamp")),
                narrative=str(row.get("narrative", row.get("asset_symbol", "BTC"))),
                market_cap=row.get("market_cap"),
                previous_market_cap=row.get("previous_market_cap"),
                volume=row.get("volume"),
                previous_volume=row.get("previous_volume"),
                coinbase_price=row.get("coinbase_price"),
                global_spot_price=row.get("global_spot_price"),
                etf_inflow=row.get("etf_inflow"),
                exchange_inflow=row.get("exchange_inflow"),
                funding_rate=row.get("funding_rate"),
                open_interest=row.get("open_interest"),
                previous_open_interest=row.get("previous_open_interest"),
                stablecoin_supply=row.get("stablecoin_supply"),
                previous_stablecoin_supply=row.get("previous_stablecoin_supply"),
                buy_volume=row.get("buy_volume"),
                sell_volume=row.get("sell_volume"),
            )
        )
    return inputs


def cumulative_volume_delta(buy_volume: float | None, sell_volume: float | None) -> float:
    return clean_number(buy_volume, 0.0) - clean_number(sell_volume, 0.0)


def stablecoin_growth_rate(current_supply: float | None, previous_supply: float | None) -> float:
    current = clean_positive(current_supply, 0.0)
    previous = clean_positive(previous_supply, current)
    if previous <= 0.0:
        return 0.0
    return clamp((current - previous) / previous, -1.0, 10.0)


def stablecoin_velocity(volume: float | None, stablecoin_supply: float | None) -> float:
    supply = clean_positive(stablecoin_supply, 0.0)
    if supply <= 0.0:
        return 0.0
    return clamp(clean_positive(volume, 0.0) / supply, 0.0, 100.0)


def coinbase_premium(coinbase_price: float | None, global_spot_price: float | None) -> float:
    spot = clean_positive(global_spot_price, 0.0)
    if spot <= 0.0:
        return 0.0
    return clamp((clean_positive(coinbase_price, spot) - spot) / spot, -1.0, 1.0)


def open_interest_growth(open_interest: float | None, previous_open_interest: float | None) -> float:
    current = clean_positive(open_interest, 0.0)
    previous = clean_positive(previous_open_interest, current)
    if previous <= 0.0:
        return 0.0
    return clamp((current - previous) / previous, -1.0, 10.0)


def funding_stress_score(funding_rate: float | None) -> float:
    funding = abs(clean_number(funding_rate, 0.0))
    return clamp(funding / 0.05 * 100.0, 0.0, 100.0)


def market_cap_momentum(item: CryptoNarrativeInput) -> float:
    current = clean_positive(item.market_cap, 100.0)
    previous = clean_positive(item.previous_market_cap, current)
    if previous <= 0.0:
        return 50.0
    return clamp(50.0 + ((current - previous) / previous) * 500.0, 0.0, 100.0)


def volume_liquidity_score(volume: float | None, previous_volume: float | None) -> float:
    current = clean_positive(volume, 0.0)
    previous = clean_positive(previous_volume, current)
    if current <= 0.0 and previous <= 0.0:
        return 50.0
    if previous <= 0.0:
        return 75.0
    return clamp(50.0 + ((current - previous) / previous) * 200.0, 0.0, 100.0)


def narrative_similarity_score(current_vector: Sequence[float], history: Sequence[CryptoNarrativeMetrics]) -> float:
    if not history:
        return 0.0
    return clamp(max(cosine_similarity(current_vector, metrics_vector(metric)) for metric in history) * 100.0, 0.0, 100.0)


def metrics_vector(metric: CryptoNarrativeMetrics) -> list[float]:
    return provisional_vector(
        metric.narrative_health,
        metric.stress_score,
        metric.rotation_score,
        metric.crash_probability,
        metric.pump_probability,
    )


def provisional_vector(health: float, stress: float, rotation: float, crash: float, pump: float) -> list[float]:
    return [
        clamp(health, 0.0, 100.0) / 100.0,
        clamp(stress, 0.0, 100.0) / 100.0,
        clamp(rotation, 0.0, 100.0) / 100.0,
        clamp(crash, 0.0, 1.0),
        clamp(pump, 0.0, 1.0),
    ]


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


def weighted_score(*components: tuple[float, float]) -> float:
    total = sum(weight for _value, weight in components)
    if total <= 0.0:
        return 0.0
    return clamp(sum(clamp(value, 0.0, 100.0) * weight for value, weight in components) / total, 0.0, 100.0)


def normalized_signed_score(value: float | None) -> float:
    return clamp(50.0 + math.tanh(clean_number(value, 0.0)) * 50.0, 0.0, 100.0)


def normalize_narrative(narrative: str) -> str:
    return narrative.upper().replace("-", "_").replace(" ", "_")


def default_input(narrative: str) -> CryptoNarrativeInput:
    return CryptoNarrativeInput(timestamp=datetime.now(timezone.utc), narrative=narrative)


def uniform_row() -> dict[str, float]:
    return {state: 1.0 / len(TRANSITION_STATES) for state in TRANSITION_STATES}


def clean_number(value: float | int | None, default: float) -> float:
    if value is None:
        return default
    parsed = float(value)
    if math.isnan(parsed):
        return default
    return parsed


def clean_positive(value: float | int | None, default: float) -> float:
    return max(0.0, clean_number(value, default))
