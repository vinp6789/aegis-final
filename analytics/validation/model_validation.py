from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable, Sequence

from analytics.common import clamp
from analytics.validation.calibration import brier_score, expected_calibration_error


MODEL_INVENTORY = (
    {
        "model": "Regime classifier",
        "inputs": "liquidity, breadth, concentration, volatility",
        "outputs": "RISK_ON, NEUTRAL, RISK_OFF, CRISIS",
        "training_method": "rules-based classifier",
        "calibration_method": "bounded probability from stress score",
        "validation_status": "PARTIAL",
    },
    {
        "model": "HMM regime model",
        "inputs": "liquidity, credit stress, recovery, valuation, return, drawdown, panic",
        "outputs": "RECOVERY, EXPANSION, LATE_CYCLE, RECESSION, PANIC",
        "training_method": "fixed transition/emission priors with forward inference",
        "calibration_method": "maturity shrinkage of probability and confidence",
        "validation_status": "PARTIAL",
    },
    {
        "model": "Probability engine",
        "inputs": "liquidity, breadth, concentration, volatility, regime, backtest, discovery",
        "outputs": "multi-horizon crash/stress/liquidity/crypto probabilities",
        "training_method": "weighted ensemble with PAVA monotonicity",
        "calibration_method": "conservative shrinkage plus stored calibrator hooks",
        "validation_status": "PARTIAL",
    },
    {
        "model": "Buy/Hold/Sell engine",
        "inputs": "panic, recovery, valuation, confidence",
        "outputs": "buy_score, hold_score, sell_score",
        "training_method": "decision scoring formula",
        "calibration_method": "forecast maturity and reliability adjustment",
        "validation_status": "PARTIAL",
    },
    {
        "model": "Recovery probability",
        "inputs": "panic, systemic stress, liquidity, credit repair, expected return/drawdown",
        "outputs": "recovery_probability_12m, recovery_probability_24m",
        "training_method": "bounded composite formula",
        "calibration_method": "maturity shrinkage through downstream confidence",
        "validation_status": "PARTIAL",
    },
    {
        "model": "Valuation model",
        "inputs": "CAPE, earnings yield, dividend yield, market-cap/GDP",
        "outputs": "valuation_score, valuation_risk, valuation_percentile",
        "training_method": "relative valuation composite",
        "calibration_method": "historical cheap/expensive ranges",
        "validation_status": "PARTIAL",
    },
    {
        "model": "Credit stress model",
        "inputs": "BAA/AAA, HY spread, TED, CP spread, yield curve, HYG/LQD proxy",
        "outputs": "credit_stress_index",
        "training_method": "spread-normalized composite",
        "calibration_method": "bounded historical stress ranges",
        "validation_status": "PARTIAL",
    },
    {
        "model": "Crisis replay engine",
        "inputs": "forecast history, realized returns, crisis analog templates",
        "outputs": "crisis similarity, replay score, lead time",
        "training_method": "historical replay and analog matching",
        "calibration_method": "coverage-aware reliability discount",
        "validation_status": "PARTIAL",
    },
    {
        "model": "Gold/Silver engine",
        "inputs": "liquidity, credit, inflation, real rates, DXY, gold/silver ratio",
        "outputs": "gold/silver probabilities, scores, return/drawdown",
        "training_method": "scenario and analog scoring",
        "calibration_method": "probability shrinkage through forecast reliability",
        "validation_status": "PARTIAL",
    },
    {
        "model": "Confidence and signal quality",
        "inputs": "agreement, backtest consistency, regime stability, crisis replay, maturity",
        "outputs": "model_confidence, signal_quality, forecast_reliability",
        "training_method": "diagnostic composite",
        "calibration_method": "explicit maturity and coverage penalties",
        "validation_status": "PARTIAL",
    },
)

HISTORICAL_PERIODS = (
    {"period": "1929", "actual_outcome": "major crash and multi-year drawdown", "expected_lead_time_months": 5.0},
    {"period": "1973", "actual_outcome": "inflation shock and bear market", "expected_lead_time_months": 4.0},
    {"period": "1987", "actual_outcome": "fast crash, rapid partial recovery", "expected_lead_time_months": 2.0},
    {"period": "2000", "actual_outcome": "valuation-led equity bear market", "expected_lead_time_months": 7.0},
    {"period": "2008", "actual_outcome": "credit crisis and deep recession", "expected_lead_time_months": 9.0},
    {"period": "2020", "actual_outcome": "pandemic shock and liquidity response", "expected_lead_time_months": 1.0},
    {"period": "2022", "actual_outcome": "inflation and liquidity shock", "expected_lead_time_months": 3.0},
)


@dataclass(frozen=True)
class ForecastValidationSample:
    probability: float
    outcome: int
    lead_time_months: float = 0.0
    avoided_drawdown: float = 0.0


def conservative_probability(probability: float, maturity: float, *, neutral: float = 0.5) -> float:
    maturity_weight = clamp(maturity, 0.0, 100.0) / 100.0
    shrink = 0.35 + maturity_weight * 0.65
    return round(clamp(neutral + (clamp(probability, 0.0, 1.0) - neutral) * shrink, 0.0, 1.0), 6)


def conservative_score(score: float, maturity: float, *, neutral: float = 50.0) -> float:
    maturity_weight = clamp(maturity, 0.0, 100.0) / 100.0
    shrink = 0.40 + maturity_weight * 0.60
    return round(clamp(neutral + (clamp(score, 0.0, 100.0) - neutral) * shrink, 0.0, 100.0), 6)


def calculate_validation_scores(
    *,
    data_completeness: float,
    model_confidence: float,
    forecast_history_count: int,
    mature_sample_count: int,
    crisis_coverage: float,
    walk_forward_score: float,
    crisis_replay_score: float,
    calibration_error: float,
) -> dict[str, float | str]:
    pipeline_health = clamp(data_completeness * 0.55 + 45.0, 0.0, 100.0)
    forecast_maturity = clamp(min(forecast_history_count / 52.0, 1.0) * 55.0 + min(mature_sample_count / 20.0, 1.0) * 45.0, 0.0, 100.0)
    historical_validation_coverage = clamp(crisis_coverage * 0.45 + min(mature_sample_count / 20.0, 1.0) * 55.0, 0.0, 100.0)
    reliability_penalty = clamp(calibration_error * 100.0, 0.0, 35.0)
    signal_quality = clamp(
        data_completeness * 0.22
        + model_confidence * 0.18
        + forecast_maturity * 0.18
        + historical_validation_coverage * 0.18
        + walk_forward_score * 0.12
        + crisis_replay_score * 0.12,
        0.0,
        100.0,
    )
    forecast_reliability = clamp(
        signal_quality * 0.55
        + historical_validation_coverage * 0.20
        + forecast_maturity * 0.15
        + (100.0 - reliability_penalty) * 0.10,
        0.0,
        100.0,
    )
    return {
        "pipeline_health": round(pipeline_health, 6),
        "data_completeness": round(clamp(data_completeness, 0.0, 100.0), 6),
        "model_confidence": round(clamp(model_confidence, 0.0, 100.0), 6),
        "forecast_maturity": round(forecast_maturity, 6),
        "historical_validation_coverage": round(historical_validation_coverage, 6),
        "signal_quality": round(signal_quality, 6),
        "forecast_reliability": round(forecast_reliability, 6),
        "forecast_reliability_method": (
            "Pipeline health, data completeness, model confidence, maturity, crisis coverage, "
            "walk-forward score, crisis replay, and calibration error are scored separately; "
            "confidence is discounted when history is sparse."
        ),
    }


def backtest_classification_metrics(samples: Sequence[ForecastValidationSample]) -> dict[str, float]:
    if not samples:
        return neutral_backtest_metrics()
    probabilities = [clamp(sample.probability, 0.0, 1.0) for sample in samples]
    outcomes = [int(sample.outcome) for sample in samples]
    predictions = [1 if probability >= 0.5 else 0 for probability in probabilities]
    tp = sum(1 for pred, outcome in zip(predictions, outcomes) if pred == 1 and outcome == 1)
    fp = sum(1 for pred, outcome in zip(predictions, outcomes) if pred == 1 and outcome == 0)
    tn = sum(1 for pred, outcome in zip(predictions, outcomes) if pred == 0 and outcome == 0)
    fn = sum(1 for pred, outcome in zip(predictions, outcomes) if pred == 0 and outcome == 1)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "brier_score": brier_score(probabilities, outcomes),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "roc_auc": round(roc_auc(probabilities, outcomes), 6),
        "calibration_error": expected_calibration_error(probabilities, outcomes),
        "f1_score": round(f1, 6),
        "prediction_lead_time": round(mean([sample.lead_time_months for sample in samples]), 6),
        "false_positive_rate": round(fp / (fp + tn), 6) if fp + tn else 0.0,
        "false_negative_rate": round(fn / (fn + tp), 6) if fn + tp else 0.0,
        "maximum_drawdown_avoided": round(max([sample.avoided_drawdown for sample in samples] or [0.0]), 6),
    }


def neutral_backtest_metrics() -> dict[str, float]:
    return {
        "brier_score": 0.25,
        "precision": 0.0,
        "recall": 0.0,
        "roc_auc": 0.5,
        "calibration_error": 0.0,
        "f1_score": 0.0,
        "prediction_lead_time": 0.0,
        "false_positive_rate": 0.0,
        "false_negative_rate": 0.0,
        "maximum_drawdown_avoided": 0.0,
    }


def roc_auc(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    positives = [prob for prob, outcome in zip(probabilities, outcomes) if outcome == 1]
    negatives = [prob for prob, outcome in zip(probabilities, outcomes) if outcome == 0]
    if not positives or not negatives:
        return 0.5
    wins = 0.0
    total = 0.0
    for positive in positives:
        for negative in negatives:
            total += 1.0
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / total if total else 0.5


def model_inventory() -> list[dict[str, str]]:
    return [dict(item) for item in MODEL_INVENTORY]


def historical_validation_summary() -> list[dict[str, float | str]]:
    return [dict(item) for item in HISTORICAL_PERIODS]


def validation_status_lists() -> dict[str, list[str]]:
    validated = [
        "Probability engine boundedness",
        "PAVA horizon monotonicity",
        "Walk-forward splitter integrity",
        "Calibration metric calculation",
        "Crisis analog coverage",
    ]
    calibrated = [
        "Probability engine",
        "HMM regime probability",
        "Regime confidence",
        "Gold/Silver probabilities",
        "Recovery probability",
        "Signal quality",
    ]
    unvalidated = [
        "Full live walk-forward accuracy until enough forecast_history matures",
        "Exact crisis lead-time replay before historical backfill",
    ]
    overconfident = [
        "HMM regime probability when history < 3 observations",
        "Gold/Silver probabilities when macro drivers are partial",
        "Signal quality when walk-forward samples are immature",
    ]
    return {
        "validated_models": validated,
        "calibrated_models": calibrated,
        "unvalidated_models": unvalidated,
        "overconfident_models": overconfident,
    }

