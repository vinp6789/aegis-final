from __future__ import annotations

from typing import Mapping

from analytics.common import clamp
from analytics.synthesis.probability_aggregator import ProbabilityMatrix


def decision_outputs_from_matrix(
    matrix: ProbabilityMatrix,
    *,
    credit_stress_index: float,
    valuation: Mapping[str, float | str],
    liquidity_index: float,
) -> dict[str, float]:
    probabilities = matrix.probabilities
    market_crash = probabilities["market_crash"][12]
    systemic_stress = probabilities["systemic_stress"][12]
    liquidity_contraction = probabilities["liquidity_contraction"][12]
    sector_stress = probabilities["sector_stress"][12]
    crypto_recovery = 1.0 - probabilities["crypto_risk_off"][12]
    confidence = normalize_confidence(matrix.confidence_score)
    credit_stress = clamp(credit_stress_index, 0.0, 100.0) / 100.0
    valuation_score = read_number(valuation.get("valuation_score"), 50.0) / 100.0
    valuation_risk = read_number(valuation.get("valuation_risk_score"), 50.0) / 100.0
    panic_probability = clamp(
        market_crash * 0.31
        + systemic_stress * 0.31
        + liquidity_contraction * 0.18
        + sector_stress * 0.10
        + credit_stress * 0.08
        + valuation_risk * 0.02,
        0.0,
        1.0,
    )
    recovery_probability = clamp(
        (1.0 - panic_probability) * 0.50
        + crypto_recovery * 0.25
        + (1.0 - liquidity_contraction) * 0.13
        + (1.0 - credit_stress) * 0.10
        + valuation_score * 0.02,
        0.0,
        1.0,
    )
    recovery_12m, recovery_24m = calculate_recovery_probabilities(
        market_crash_12m=market_crash,
        systemic_stress_12m=systemic_stress,
        liquidity_index=liquidity_index,
        credit_stress_index=credit_stress_index,
        recovery_signal=recovery_probability,
        expected_return_proxy=None,
        expected_drawdown_proxy=None,
    )
    return build_decision_outputs(
        credit_stress_index=credit_stress_index,
        valuation_score=read_number(valuation.get("valuation_score"), 50.0),
        valuation_risk_score=read_number(valuation.get("valuation_risk_score"), 50.0),
        valuation_percentile=read_number(valuation.get("valuation_percentile"), 50.0),
        recovery_probability_12m=recovery_12m,
        recovery_probability_24m=recovery_24m,
        panic_probability=panic_probability,
        recovery_probability=recovery_probability,
        confidence=confidence,
        market_crash_12m=market_crash,
        sector_stress_12m=sector_stress,
    )


def calculate_recovery_probabilities(
    *,
    market_crash_12m: float,
    systemic_stress_12m: float,
    liquidity_index: float,
    credit_stress_index: float,
    recovery_signal: float,
    expected_return_proxy: float | None,
    expected_drawdown_proxy: float | None,
) -> tuple[float, float]:
    crash = clamp(market_crash_12m, 0.0, 1.0)
    systemic = clamp(systemic_stress_12m, 0.0, 1.0)
    liquidity = clamp(liquidity_index, 0.0, 100.0) / 100.0
    credit_repair = 1.0 - clamp(credit_stress_index, 0.0, 100.0) / 100.0
    recovery_base = clamp(recovery_signal, 0.0, 1.0)
    positive_return = clamp(((expected_return_proxy if expected_return_proxy is not None else 0.0) + 0.25) / 0.50, 0.0, 1.0)
    drawdown_repair = 1.0 - clamp(expected_drawdown_proxy if expected_drawdown_proxy is not None else max(crash, systemic) * 0.45, 0.0, 0.80) / 0.80
    stress_reset = clamp((crash + systemic) / 2.0, 0.0, 1.0)
    moderate_stress = clamp(1.0 - abs(stress_reset - 0.45) / 0.45, 0.0, 1.0)
    recovery_12m = (
        recovery_base * 0.28
        + liquidity * 0.20
        + credit_repair * 0.18
        + positive_return * 0.14
        + drawdown_repair * 0.10
        + moderate_stress * 0.10
    )
    recovery_24m = recovery_12m * 0.58 + liquidity * 0.18 + credit_repair * 0.14 + drawdown_repair * 0.10
    return round(clamp(recovery_12m * 100.0, 0.0, 100.0), 6), round(clamp(recovery_24m * 100.0, 0.0, 100.0), 6)


def build_decision_outputs(
    *,
    credit_stress_index: float,
    valuation_score: float,
    valuation_risk_score: float,
    valuation_percentile: float,
    recovery_probability_12m: float,
    recovery_probability_24m: float,
    panic_probability: float,
    recovery_probability: float,
    confidence: float,
    market_crash_12m: float,
    sector_stress_12m: float,
) -> dict[str, float]:
    panic = clamp(panic_probability, 0.0, 1.0)
    recovery = clamp(recovery_probability, 0.0, 1.0)
    confidence = normalize_confidence(confidence)
    recovery_12m = clamp(recovery_probability_12m, 0.0, 100.0) / 100.0
    recovery_24m = clamp(recovery_probability_24m, 0.0, 100.0) / 100.0
    valuation_attractiveness = clamp(valuation_score, 0.0, 100.0) / 100.0
    valuation_risk = clamp(valuation_risk_score, 0.0, 100.0) / 100.0
    conviction = 0.55 + confidence * 0.45
    raw_buy = max(0.01, (recovery * 0.62 + recovery_12m * 0.25 + valuation_attractiveness * 0.13) * conviction)
    raw_sell = max(0.01, (panic * 0.78 + (1.0 - recovery_12m) * 0.12 + valuation_risk * 0.10) * conviction)
    raw_hold = max(0.01, (1.0 - abs(recovery - panic)) * (1.15 - conviction))
    total = raw_buy + raw_hold + raw_sell
    buy_score = round(raw_buy / total * 100.0, 2)
    sell_score = round(raw_sell / total * 100.0, 2)
    credit_stress = clamp(credit_stress_index, 0.0, 100.0) / 100.0
    expected_return = clamp(recovery * 0.16 + recovery_12m * 0.07 + recovery_24m * 0.04 + valuation_attractiveness * 0.06 - panic * 0.27 - credit_stress * 0.05 + (confidence - 0.50) * 0.04, -0.50, 0.50)
    expected_drawdown = clamp(panic * 0.38 + market_crash_12m * 0.10 + sector_stress_12m * 0.05 + credit_stress * 0.10 + valuation_risk * 0.08, 0.0, 0.80)
    return {
        "credit_stress_index": round(clamp(credit_stress_index, 0.0, 100.0), 6),
        "valuation_score": round(clamp(valuation_score, 0.0, 100.0), 6),
        "valuation_risk_score": round(clamp(valuation_risk_score, 0.0, 100.0), 6),
        "valuation_percentile": round(clamp(valuation_percentile, 0.0, 100.0), 6),
        "recovery_probability_12m": round(clamp(recovery_probability_12m, 0.0, 100.0), 6),
        "recovery_probability_24m": round(clamp(recovery_probability_24m, 0.0, 100.0), 6),
        "buy_score": buy_score,
        "hold_score": round(max(0.0, 100.0 - buy_score - sell_score), 2),
        "sell_score": sell_score,
        "expected_return_12m": round(expected_return, 6),
        "expected_drawdown_12m": round(expected_drawdown, 6),
    }


def normalize_confidence(value: float) -> float:
    confidence = read_number(value, 0.50)
    if confidence > 1.0:
        confidence /= 100.0
    return clamp(confidence, 0.0, 1.0)


def read_number(value: float | str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
