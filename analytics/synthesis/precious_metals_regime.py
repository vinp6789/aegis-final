from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from analytics.common import clamp


@dataclass(frozen=True)
class PreciousMetalsInput:
    liquidity_index: float | None = None
    credit_stress_index: float | None = None
    market_crash_probability: float | None = None
    systemic_stress_probability: float | None = None
    inflation_pressure: float | None = None
    real_rate_pressure: float | None = None
    dollar_pressure: float | None = None
    gold_silver_ratio: float | None = None
    gold_momentum: float | None = None
    silver_momentum: float | None = None
    central_bank_gold_accumulation: float | None = None
    gold_etf_flow: float | None = None
    silver_etf_flow: float | None = None


@dataclass(frozen=True)
class HistoricalAnalog:
    period: str
    metal: str
    regime: str
    similarity_score: float
    rationale: str


@dataclass(frozen=True)
class PreciousMetalsRegime:
    gold_bull_probability: float
    gold_bear_probability: float
    gold_acceleration_probability: float
    gold_correction_probability: float
    silver_bull_probability: float
    silver_bear_probability: float
    silver_acceleration_probability: float
    silver_correction_probability: float
    gold_buy_score: float
    gold_hold_score: float
    gold_sell_score: float
    silver_buy_score: float
    silver_hold_score: float
    silver_sell_score: float
    gold_expected_return_12m: float
    gold_expected_drawdown_12m: float
    silver_expected_return_12m: float
    silver_expected_drawdown_12m: float
    gold_silver_ratio: float
    gold_relative_value_score: float
    silver_relative_value_score: float
    gold_top_drivers: list[dict[str, float | str]]
    silver_top_drivers: list[dict[str, float | str]]
    historical_precious_metal_analogs: list[HistoricalAnalog]
    validation_method: str

    def to_dict(self) -> dict[str, object]:
        return {
            "gold_bull_probability": self.gold_bull_probability,
            "gold_bear_probability": self.gold_bear_probability,
            "gold_acceleration_probability": self.gold_acceleration_probability,
            "gold_correction_probability": self.gold_correction_probability,
            "silver_bull_probability": self.silver_bull_probability,
            "silver_bear_probability": self.silver_bear_probability,
            "silver_acceleration_probability": self.silver_acceleration_probability,
            "silver_correction_probability": self.silver_correction_probability,
            "gold_buy_score": self.gold_buy_score,
            "gold_hold_score": self.gold_hold_score,
            "gold_sell_score": self.gold_sell_score,
            "silver_buy_score": self.silver_buy_score,
            "silver_hold_score": self.silver_hold_score,
            "silver_sell_score": self.silver_sell_score,
            "gold_expected_return_12m": self.gold_expected_return_12m,
            "gold_expected_drawdown_12m": self.gold_expected_drawdown_12m,
            "silver_expected_return_12m": self.silver_expected_return_12m,
            "silver_expected_drawdown_12m": self.silver_expected_drawdown_12m,
            "gold_silver_ratio": self.gold_silver_ratio,
            "gold_relative_value_score": self.gold_relative_value_score,
            "silver_relative_value_score": self.silver_relative_value_score,
            "gold_top_drivers": self.gold_top_drivers,
            "silver_top_drivers": self.silver_top_drivers,
            "historical_precious_metal_analogs": [
                {
                    "period": analog.period,
                    "metal": analog.metal,
                    "regime": analog.regime,
                    "similarity_score": analog.similarity_score,
                    "rationale": analog.rationale,
                }
                for analog in self.historical_precious_metal_analogs
            ],
            "validation_method": self.validation_method,
        }


@dataclass(frozen=True)
class AnalogTemplate:
    period: str
    metal: str
    regime: str
    vector: tuple[float, float, float, float, float, float]
    rationale: str


class PreciousMetalsRegimeEngine:
    def evaluate(self, input_data: PreciousMetalsInput) -> PreciousMetalsRegime:
        liquidity = index_0_100(input_data.liquidity_index, 55.0) / 100.0
        credit = index_0_100(input_data.credit_stress_index, 45.0) / 100.0
        crash = probability(input_data.market_crash_probability, 0.45)
        systemic = probability(input_data.systemic_stress_probability, 0.45)
        inflation = index_0_100(input_data.inflation_pressure, 50.0) / 100.0
        real_rate = index_0_100(input_data.real_rate_pressure, 50.0) / 100.0
        dollar = index_0_100(input_data.dollar_pressure, 50.0) / 100.0
        ratio = clamp(input_data.gold_silver_ratio or 85.0, 20.0, 150.0)
        gold_momentum = normalized_momentum(input_data.gold_momentum)
        silver_momentum = normalized_momentum(input_data.silver_momentum)
        central_bank_gold = index_0_100(input_data.central_bank_gold_accumulation, 50.0) / 100.0
        gold_etf = index_0_100(input_data.gold_etf_flow, 50.0) / 100.0
        silver_etf = index_0_100(input_data.silver_etf_flow, 50.0) / 100.0
        gold_value, silver_value = relative_value_scores(ratio)

        macro_risk = clamp((crash + systemic + credit) / 3.0, 0.0, 1.0)
        gold_bull = probability_score(
            0.16 + liquidity * 0.13 + inflation * 0.16 + real_rate * 0.15 + macro_risk * 0.14
            + gold_momentum * 0.12 + central_bank_gold * 0.09 + gold_etf * 0.06 - dollar * 0.11
        )
        gold_bear = probability_score(
            0.14 + dollar * 0.22 + (1.0 - inflation) * 0.12 + (1.0 - liquidity) * 0.14
            + (1.0 - gold_momentum) * 0.12 - macro_risk * 0.05 - central_bank_gold * 0.05
        )
        gold_acceleration = probability_score(gold_bull * 0.46 + inflation * 0.14 + real_rate * 0.14 + gold_momentum * 0.18 + gold_etf * 0.08)
        gold_correction = probability_score(gold_bear * 0.50 + dollar * 0.22 + max(0.0, gold_bull - 0.70) * 0.20)

        silver_value_signal = silver_value / 100.0
        silver_bull = probability_score(
            0.14 + liquidity * 0.18 + inflation * 0.14 + silver_value_signal * 0.16
            + silver_momentum * 0.16 + silver_etf * 0.07 + (1.0 - credit) * 0.08 - systemic * 0.07
        )
        silver_bear = probability_score(
            0.14 + credit * 0.20 + systemic * 0.15 + dollar * 0.14 + (1.0 - liquidity) * 0.12
            + (1.0 - silver_momentum) * 0.13 - silver_value_signal * 0.08
        )
        silver_acceleration = probability_score(silver_bull * 0.44 + silver_value_signal * 0.16 + liquidity * 0.14 + inflation * 0.10 + silver_momentum * 0.16)
        silver_correction = probability_score(silver_bear * 0.55 + credit * 0.18 + max(0.0, silver_bull - 0.70) * 0.22)

        gold_buy, gold_hold, gold_sell = buy_hold_sell(gold_bull, gold_bear, gold_correction, gold_value / 100.0)
        silver_buy, silver_hold, silver_sell = buy_hold_sell(silver_bull, silver_bear, silver_correction, silver_value_signal)
        analogs = find_analogs((liquidity, inflation, credit, real_rate, dollar, macro_risk))
        analog_bias = analog_return_bias(analogs)

        gold_expected_return = clamp(gold_bull * 0.15 + gold_acceleration * 0.08 + gold_momentum * 0.05 + analog_bias * 0.04 - gold_bear * 0.12 - credit * 0.03 - dollar * 0.03, -0.40, 0.60)
        gold_expected_drawdown = clamp(gold_bear * 0.18 + gold_correction * 0.16 + dollar * 0.06 + credit * 0.05, 0.0, 0.55)
        silver_expected_return = clamp(silver_bull * 0.22 + silver_acceleration * 0.11 + silver_momentum * 0.07 + analog_bias * 0.06 - silver_bear * 0.18 - credit * 0.05 - dollar * 0.03, -0.55, 0.90)
        silver_expected_drawdown = clamp(silver_bear * 0.26 + silver_correction * 0.22 + credit * 0.10 + systemic * 0.06, 0.0, 0.75)
        gold_drivers = top_drivers(
            ("Real rate pressure", real_rate, "supports gold when real yields are unfavorable"),
            ("Inflation pressure", inflation, "supports hard-asset demand"),
            ("Gold momentum", gold_momentum, "confirms trend participation"),
            ("DXY pressure", -dollar, "strong dollar suppresses gold"),
            ("Central bank accumulation", central_bank_gold, "supports structural demand"),
            ("Credit/liquidity stress", macro_risk, "raises hedge demand"),
        )
        silver_drivers = top_drivers(
            ("Silver momentum", silver_momentum, "confirms high-beta trend participation"),
            ("Gold/Silver relative value", silver_value_signal, "high ratio favors silver catch-up potential"),
            ("Liquidity", liquidity, "supports cyclical precious metals demand"),
            ("DXY pressure", -dollar, "strong dollar suppresses silver"),
            ("Credit stress", -credit, "credit stress can pressure cyclical silver"),
            ("Silver ETF flow", silver_etf, "supports incremental demand"),
        )

        return PreciousMetalsRegime(
            gold_bull_probability=round(gold_bull, 6),
            gold_bear_probability=round(gold_bear, 6),
            gold_acceleration_probability=round(gold_acceleration, 6),
            gold_correction_probability=round(gold_correction, 6),
            silver_bull_probability=round(silver_bull, 6),
            silver_bear_probability=round(silver_bear, 6),
            silver_acceleration_probability=round(silver_acceleration, 6),
            silver_correction_probability=round(silver_correction, 6),
            gold_buy_score=gold_buy,
            gold_hold_score=gold_hold,
            gold_sell_score=gold_sell,
            silver_buy_score=silver_buy,
            silver_hold_score=silver_hold,
            silver_sell_score=silver_sell,
            gold_expected_return_12m=round(gold_expected_return, 6),
            gold_expected_drawdown_12m=round(gold_expected_drawdown, 6),
            silver_expected_return_12m=round(silver_expected_return, 6),
            silver_expected_drawdown_12m=round(silver_expected_drawdown, 6),
            gold_silver_ratio=round(ratio, 6),
            gold_relative_value_score=round(gold_value, 6),
            silver_relative_value_score=round(silver_value, 6),
            gold_top_drivers=gold_drivers,
            silver_top_drivers=silver_drivers,
            historical_precious_metal_analogs=analogs,
            validation_method=(
                "Scenario-style environment matching against 1970s inflation, 1980 peak, "
                "2001-2011 bull, 2008 liquidity response, 2011 peak, and 2020 pandemic templates."
            ),
        )


def relative_value_scores(ratio: float) -> tuple[float, float]:
    normalized = clamp((ratio - 45.0) / (120.0 - 45.0), 0.0, 1.0)
    gold_value = (1.0 - normalized) * 100.0
    silver_value = normalized * 100.0
    return gold_value, silver_value


def buy_hold_sell(bull: float, bear: float, correction: float, value_score: float) -> tuple[float, float, float]:
    buy_raw = max(0.01, bull * 0.70 + value_score * 0.30)
    sell_raw = max(0.01, bear * 0.55 + correction * 0.35 + (1.0 - value_score) * 0.10)
    hold_raw = max(0.01, 1.0 - abs(buy_raw - sell_raw))
    total = buy_raw + hold_raw + sell_raw
    buy = round(buy_raw / total * 100.0, 2)
    sell = round(sell_raw / total * 100.0, 2)
    hold = round(max(0.0, 100.0 - buy - sell), 2)
    return buy, hold, sell


def normalized_momentum(value: float | None) -> float:
    if value is None:
        return 0.50
    return clamp((float(value) + 0.20) / 0.40, 0.0, 1.0)


def top_drivers(*drivers: tuple[str, float, str]) -> list[dict[str, float | str]]:
    ranked = sorted(drivers, key=lambda item: abs(item[1] - 0.50), reverse=True)
    output = []
    for name, value, rationale in ranked[:4]:
        normalized = clamp(value if value >= 0.0 else 1.0 + value, 0.0, 1.0)
        direction = "bullish" if value >= 0.50 else "bearish"
        output.append(
            {
                "driver": name,
                "direction": direction,
                "strength": round(abs(normalized - 0.50) * 2.0, 6),
                "rationale": rationale,
            }
        )
    return output


def find_analogs(current: tuple[float, float, float, float, float, float], *, top_k: int = 5) -> list[HistoricalAnalog]:
    ranked = []
    for template in ANALOG_TEMPLATES:
        distance = math.sqrt(sum((left - right) ** 2 for left, right in zip(current, template.vector)))
        similarity = clamp((1.0 - distance / math.sqrt(len(current))) * 100.0, 0.0, 100.0)
        ranked.append(
            HistoricalAnalog(
                period=template.period,
                metal=template.metal,
                regime=template.regime,
                similarity_score=round(similarity, 6),
                rationale=template.rationale,
            )
        )
    ranked.sort(key=lambda analog: analog.similarity_score, reverse=True)
    return ranked[:top_k]


def analog_return_bias(analogs: Sequence[HistoricalAnalog]) -> float:
    if not analogs:
        return 0.0
    score = 0.0
    total = 0.0
    for analog in analogs:
        weight = analog.similarity_score / 100.0
        total += weight
        if analog.regime in {"ACCUMULATION", "BULL_RUN"}:
            score += weight
        elif analog.regime in {"DISTRIBUTION", "CORRECTION"}:
            score -= weight
    return clamp(score / total if total else 0.0, -1.0, 1.0)


def probability(value: float | None, default: float) -> float:
    return clamp(default if value is None else float(value), 0.0, 1.0)


def probability_score(value: float) -> float:
    return clamp(value, 0.0, 1.0)


def index_0_100(value: float | None, default: float) -> float:
    return clamp(default if value is None else float(value), 0.0, 100.0)


ANALOG_TEMPLATES = (
    AnalogTemplate("1971 Nixon Shock", "Gold", "ACCUMULATION", (0.45, 0.75, 0.45, 0.80, 0.45, 0.55), "Fiat reset, inflation pressure, negative real-rate impulse."),
    AnalogTemplate("1973 Oil Crisis", "Gold", "BULL_RUN", (0.40, 0.90, 0.65, 0.85, 0.55, 0.70), "Inflation shock with rising macro and credit stress."),
    AnalogTemplate("1979 Inflation Crisis", "Gold", "BULL_RUN", (0.35, 0.95, 0.75, 0.90, 0.50, 0.80), "Late-cycle inflation panic and hard-asset demand."),
    AnalogTemplate("2001 Dotcom Bust", "Gold", "ACCUMULATION", (0.65, 0.45, 0.55, 0.70, 0.45, 0.65), "Equity stress and easier liquidity after growth shock."),
    AnalogTemplate("2008 Post-Liquidity Response", "Gold", "ACCUMULATION", (0.80, 0.35, 0.95, 0.80, 0.60, 0.90), "Crisis credit stress followed by aggressive liquidity response."),
    AnalogTemplate("2020 Pandemic", "Gold", "BULL_RUN", (0.95, 0.55, 0.85, 0.85, 0.45, 0.85), "Extreme liquidity expansion and crisis hedge demand."),
    AnalogTemplate("Recent Central Bank Accumulation Cycle", "Gold", "ACCUMULATION", (0.55, 0.65, 0.45, 0.70, 0.55, 0.45), "Persistent official-sector accumulation and reserve diversification."),
    AnalogTemplate("1980 Peak", "Gold", "DISTRIBUTION", (0.25, 0.95, 0.70, 0.30, 0.80, 0.65), "Policy tightening and exhausted inflation hedge positioning."),
    AnalogTemplate("2011 Peak", "Gold", "DISTRIBUTION", (0.60, 0.45, 0.70, 0.45, 0.75, 0.65), "Post-crisis peak with rising dollar and fading acceleration."),
    AnalogTemplate("2013 Taper Shock", "Gold", "CORRECTION", (0.45, 0.35, 0.45, 0.25, 0.80, 0.45), "Real-rate and dollar shock after policy repricing."),
    AnalogTemplate("Strong USD Cycles", "Gold", "CORRECTION", (0.45, 0.30, 0.35, 0.25, 0.90, 0.35), "Dollar strength and positive real-rate pressure."),
    AnalogTemplate("1979-1980", "Silver", "BULL_RUN", (0.35, 0.95, 0.75, 0.90, 0.50, 0.80), "Inflation panic with high-beta precious metal demand."),
    AnalogTemplate("2003-2006", "Silver", "BULL_RUN", (0.70, 0.55, 0.30, 0.60, 0.35, 0.35), "Liquidity expansion and cyclical reflation."),
    AnalogTemplate("2009-2011", "Silver", "BULL_RUN", (0.85, 0.50, 0.70, 0.75, 0.45, 0.65), "Post-crisis liquidity and hard-asset acceleration."),
    AnalogTemplate("2020-2021", "Silver", "BULL_RUN", (0.95, 0.60, 0.75, 0.80, 0.45, 0.70), "Pandemic liquidity response and reflation impulse."),
    AnalogTemplate("1980 Crash", "Silver", "CORRECTION", (0.25, 0.95, 0.80, 0.20, 0.85, 0.75), "Speculative peak followed by policy and liquidity shock."),
    AnalogTemplate("2011 Peak", "Silver", "DISTRIBUTION", (0.60, 0.45, 0.70, 0.40, 0.80, 0.65), "Parabolic move exhaustion and dollar/real-rate pressure."),
    AnalogTemplate("2021-2022 Correction", "Silver", "CORRECTION", (0.50, 0.60, 0.55, 0.25, 0.85, 0.50), "Tighter policy, strong dollar, and fading liquidity impulse."),
)
