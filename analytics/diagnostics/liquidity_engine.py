from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from statistics import mean, pstdev
from typing import Any, Mapping, Protocol, Sequence

from analytics.common import clamp, normalize_to_100


@dataclass(frozen=True)
class LiquidityInput:
    timestamp: datetime
    values: Mapping[str, float | int | None]


@dataclass(frozen=True)
class LiquidityIndexPoint:
    timestamp: datetime
    raw_value: float
    normalized_value: float


@dataclass(frozen=True)
class LiquiditySnapshot:
    timestamp: datetime
    us_liquidity_index: float
    india_liquidity_index: float
    crypto_liquidity_index: float
    global_liquidity_index: float
    liquidity_transmission_score: float


class FeastOfflineStore(Protocol):
    def get_historical_features(self, *, features: Sequence[str], entity_df: Any) -> Any:
        ...


class LiquidityEngine:
    """Phase 7 liquidity index calculator with bounded daily outputs."""

    def us_liquidity_raw(self, values: Mapping[str, float | int | None]) -> float:
        fed_balance_sheet = clean_number(values.get("fed_balance_sheet"))
        bank_reserves = clean_number(values.get("bank_reserves"))
        tga = clean_number(values.get("tga"))
        reverse_repo = clean_number(values.get("reverse_repo"))
        return fed_balance_sheet + bank_reserves - tga - reverse_repo

    def india_liquidity_raw(self, values: Mapping[str, float | int | None]) -> float:
        return (
            clean_number(values.get("rbi_liquidity"))
            + clean_number(values.get("laf"))
            + clean_number(values.get("msf"))
            + clean_number(values.get("sdf"))
            + clean_number(values.get("fii_flows"))
            + clean_number(values.get("dii_flows"))
        )

    def crypto_liquidity_raw(self, values: Mapping[str, float | int | None]) -> float:
        return (
            clean_number(values.get("stablecoin_supply_growth"))
            + clean_number(values.get("usdt_growth"))
            + clean_number(values.get("usdc_growth"))
            + clean_number(values.get("coinbase_premium"))
            + clean_number(values.get("btc_spot_cvd"))
        )

    def global_liquidity_raw(
        self,
        *,
        us_raw: float,
        india_raw: float,
        macro_values: Mapping[str, float | int | None],
    ) -> float:
        macro_liquidity = clean_number(macro_values.get("global_macro_liquidity"))
        global_credit = clean_number(macro_values.get("global_credit_growth"))
        dollar_liquidity = clean_number(macro_values.get("dollar_liquidity"))
        return us_raw * 0.45 + india_raw * 0.25 + macro_liquidity * 0.20 + global_credit * 0.05 + dollar_liquidity * 0.05

    def build_daily_indices(
        self,
        *,
        us_inputs: Sequence[LiquidityInput],
        india_inputs: Sequence[LiquidityInput],
        crypto_inputs: Sequence[LiquidityInput],
        macro_inputs: Sequence[LiquidityInput],
        transmission_window: int = 5,
    ) -> list[LiquiditySnapshot]:
        if transmission_window < 2:
            raise ValueError("transmission_window must be at least 2")

        dates = sorted(
            {
                *[item.timestamp.date() for item in us_inputs],
                *[item.timestamp.date() for item in india_inputs],
                *[item.timestamp.date() for item in crypto_inputs],
                *[item.timestamp.date() for item in macro_inputs],
            }
        )
        if not dates:
            return []

        us_by_date = by_date(us_inputs)
        india_by_date = by_date(india_inputs)
        crypto_by_date = by_date(crypto_inputs)
        macro_by_date = by_date(macro_inputs)
        us_raw = [self.us_liquidity_raw(us_by_date.get(day, {})) for day in dates]
        india_raw = [self.india_liquidity_raw(india_by_date.get(day, {})) for day in dates]
        crypto_raw = [self.crypto_liquidity_raw(crypto_by_date.get(day, {})) for day in dates]
        global_raw = [
            self.global_liquidity_raw(
                us_raw=us_value,
                india_raw=india_value,
                macro_values=macro_by_date.get(day, {}),
            )
            for day, us_value, india_value in zip(dates, us_raw, india_raw)
        ]

        us_norm = normalize_series(us_raw)
        india_norm = normalize_series(india_raw)
        crypto_norm = normalize_series(crypto_raw)
        global_norm = normalize_series(global_raw)
        transmission = transmission_scores(global_norm, india_norm, window=transmission_window)

        return [
            LiquiditySnapshot(
                timestamp=datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
                us_liquidity_index=us_norm[index],
                india_liquidity_index=india_norm[index],
                crypto_liquidity_index=crypto_norm[index],
                global_liquidity_index=global_norm[index],
                liquidity_transmission_score=transmission[index],
            )
            for index, day in enumerate(dates)
        ]

    def verify_indices(self, snapshots: Sequence[LiquiditySnapshot]) -> bool:
        return bool(snapshots) and all(
            all(
                0.0 <= value <= 100.0
                for value in (
                    snapshot.us_liquidity_index,
                    snapshot.india_liquidity_index,
                    snapshot.crypto_liquidity_index,
                    snapshot.global_liquidity_index,
                    snapshot.liquidity_transmission_score,
                )
            )
            for snapshot in snapshots
        )

    def fetch_feast_liquidity_features(
        self,
        offline_store: FeastOfflineStore,
        *,
        entity_df: Any,
    ) -> Any:
        features = [
            "macro_liquidity_indicators:fed_balance_sheet",
            "macro_liquidity_indicators:tga",
            "macro_liquidity_indicators:reverse_repo",
            "india_liquidity_flows:rbi_liquidity",
            "india_liquidity_flows:laf",
            "india_liquidity_flows:msf",
            "india_liquidity_flows:sdf",
            "india_liquidity_flows:fii_flows",
            "india_liquidity_flows:dii_flows",
        ]
        return offline_store.get_historical_features(features=features, entity_df=entity_df)


def normalize_series(values: Sequence[float]) -> list[float]:
    return normalize_to_100(values)


def transmission_scores(global_index: Sequence[float], india_index: Sequence[float], *, window: int) -> list[float]:
    if len(global_index) != len(india_index):
        raise ValueError("global and india index lengths must match")
    if not global_index:
        return []
    scores: list[float] = []
    for index in range(len(global_index)):
        if index < window:
            scores.append(50.0)
            continue
        global_changes = differences(global_index[index - window:index + 1])
        india_changes = differences(india_index[index - window:index + 1])
        corr = correlation(global_changes, india_changes)
        scores.append(round((corr + 1.0) * 50.0, 6))
    return scores


def differences(values: Sequence[float]) -> list[float]:
    return [float(values[index]) - float(values[index - 1]) for index in range(1, len(values))]


def correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_std = pstdev(left)
    right_std = pstdev(right)
    if left_std == 0.0 or right_std == 0.0:
        return 0.0
    left_mean = mean(left)
    right_mean = mean(right)
    cov = mean((lvalue - left_mean) * (rvalue - right_mean) for lvalue, rvalue in zip(left, right))
    return clamp(cov / (left_std * right_std), -1.0, 1.0)


def by_date(inputs: Sequence[LiquidityInput]) -> dict[date, Mapping[str, float | int | None]]:
    return {item.timestamp.date(): item.values for item in inputs}


def clean_number(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)
