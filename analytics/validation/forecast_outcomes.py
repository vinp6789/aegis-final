from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Mapping, Protocol, Sequence

from analytics.common import clamp, clip_probability, normalize_timestamp
from analytics.validation.calibration import brier_score, expected_calibration_error


ROLLING_WINDOWS_MONTHS = (3, 6, 12)


@dataclass(frozen=True)
class ForecastOutcomeRecord:
    timestamp: datetime
    probability: float | None
    realized_outcome: int | bool | None
    target_scope: str = "GLOBAL"
    forecast_type: str = "systemic_stress"
    horizon_months: int = 12
    resolved_timestamp: datetime | None = None
    factors: Mapping[str, float | int | None] | None = None
    production_weights: Mapping[str, float | int | None] | None = None


@dataclass(frozen=True)
class ForecastOutcomeComparison:
    timestamp: datetime
    resolved_timestamp: datetime
    target_scope: str
    forecast_type: str
    horizon_months: int
    probability: float
    realized_outcome: int
    predicted_outcome: int
    correct: bool
    probability_error: float
    squared_error: float
    factors: dict[str, float]
    production_weights: dict[str, float]


@dataclass(frozen=True)
class RollingValidationMetrics:
    window_months: int
    sample_count: int
    brier_score: float
    precision: float
    recall: float
    f1: float
    roc_auc: float | None
    calibration_error: float


@dataclass(frozen=True)
class ReliabilityTrend:
    direction: str
    reliability_score: float
    short_term_score: float
    long_term_score: float
    slope: float


@dataclass(frozen=True)
class DriverAttribution:
    factor: str
    contribution_score: float
    average_value: float
    sample_count: int


@dataclass(frozen=True)
class AdaptiveWeightRecommendation:
    factor: str
    current_weight: float
    recommended_weight: float
    evidence_score: float
    recommended_delta: float


@dataclass(frozen=True)
class ForecastOutcomeResearchReport:
    generated_at: datetime
    target_scope: str
    forecast_type: str
    horizon_months: int
    resolved_forecasts: int
    unresolved_forecasts: int
    rolling_metrics: dict[str, RollingValidationMetrics]
    reliability_trend: ReliabilityTrend
    correct_forecast_drivers: list[DriverAttribution]
    incorrect_forecast_drivers: list[DriverAttribution]
    adaptive_weight_recommendations: list[AdaptiveWeightRecommendation]
    research_readiness_score: float
    model_trust_score: float
    forecast_reliability_score: float


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


class ForecastOutcomeReportRepository(Protocol):
    def persist(self, connection: DbConnection, report: ForecastOutcomeResearchReport) -> None:
        ...


class ForecastOutcomeValidator:
    def __init__(self, *, threshold: float = 0.5, calibration_bins: int = 10) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if calibration_bins <= 0:
            raise ValueError("calibration_bins must be positive")
        self.threshold = threshold
        self.calibration_bins = calibration_bins

    def compare(
        self,
        records: Sequence[ForecastOutcomeRecord],
        *,
        target_scope: str = "GLOBAL",
        forecast_type: str = "systemic_stress",
        horizon_months: int = 12,
    ) -> tuple[list[ForecastOutcomeComparison], int]:
        comparisons: list[ForecastOutcomeComparison] = []
        unresolved = 0
        for record in records:
            if (
                record.target_scope != target_scope
                or record.forecast_type != forecast_type
                or int(record.horizon_months) != int(horizon_months)
            ):
                continue
            if record.realized_outcome is None:
                unresolved += 1
                continue
            probability = clip_probability(record.probability)
            outcome = safe_outcome(record.realized_outcome)
            predicted = 1 if probability >= self.threshold else 0
            resolved_at = normalize_timestamp(record.resolved_timestamp or record.timestamp)
            comparisons.append(
                ForecastOutcomeComparison(
                    timestamp=normalize_timestamp(record.timestamp),
                    resolved_timestamp=resolved_at,
                    target_scope=record.target_scope,
                    forecast_type=record.forecast_type,
                    horizon_months=int(record.horizon_months),
                    probability=probability,
                    realized_outcome=outcome,
                    predicted_outcome=predicted,
                    correct=predicted == outcome,
                    probability_error=round(abs(probability - outcome), 10),
                    squared_error=round((probability - outcome) ** 2, 10),
                    factors=clean_factor_map(record.factors),
                    production_weights=clean_weight_map(record.production_weights),
                )
            )
        comparisons.sort(key=lambda item: item.resolved_timestamp)
        return comparisons, unresolved

    def validate(
        self,
        records: Sequence[ForecastOutcomeRecord],
        *,
        target_scope: str = "GLOBAL",
        forecast_type: str = "systemic_stress",
        horizon_months: int = 12,
        as_of: datetime | None = None,
    ) -> ForecastOutcomeResearchReport:
        comparisons, unresolved = self.compare(
            records,
            target_scope=target_scope,
            forecast_type=forecast_type,
            horizon_months=horizon_months,
        )
        report_time = normalize_timestamp(as_of or datetime.now(timezone.utc))
        rolling = rolling_validation_metrics(
            comparisons,
            as_of=report_time,
            bins=self.calibration_bins,
        )
        trend = reliability_trend(rolling)
        correct, incorrect = driver_attribution(comparisons)
        recommendations = adaptive_weight_audit(comparisons)
        return ForecastOutcomeResearchReport(
            generated_at=report_time,
            target_scope=target_scope,
            forecast_type=forecast_type,
            horizon_months=horizon_months,
            resolved_forecasts=len(comparisons),
            unresolved_forecasts=unresolved,
            rolling_metrics={f"{window}M": metrics for window, metrics in rolling.items()},
            reliability_trend=trend,
            correct_forecast_drivers=correct,
            incorrect_forecast_drivers=incorrect,
            adaptive_weight_recommendations=recommendations,
            research_readiness_score=research_readiness_score(len(comparisons), rolling),
            model_trust_score=model_trust_score(rolling, trend),
            forecast_reliability_score=trend.reliability_score,
        )

    def validate_and_persist(
        self,
        connection: DbConnection,
        records: Sequence[ForecastOutcomeRecord],
        *,
        repository: ForecastOutcomeReportRepository,
        target_scope: str = "GLOBAL",
        forecast_type: str = "systemic_stress",
        horizon_months: int = 12,
        as_of: datetime | None = None,
    ) -> ForecastOutcomeResearchReport:
        report = self.validate(
            records,
            target_scope=target_scope,
            forecast_type=forecast_type,
            horizon_months=horizon_months,
            as_of=as_of,
        )
        repository.persist(connection, report)
        return report


class ForecastOutcomeAuditPersistenceAdapter:
    table_name = "data_quality_exceptions"
    columns = (
        "timestamp",
        "source_name",
        "field_name",
        "exception_type",
        "bad_value_raw",
        "severity",
    )

    def to_row(self, report: ForecastOutcomeResearchReport) -> dict[str, Any]:
        return {
            "timestamp": normalize_timestamp(report.generated_at),
            "source_name": "forecast_outcomes",
            "field_name": report.forecast_type,
            "exception_type": "FORECAST_OUTCOME_RESEARCH_REPORT",
            "bad_value_raw": json.dumps(report_to_dict(report), sort_keys=True),
            "severity": severity_for_report(report),
        }

    def persist(self, connection: DbConnection, report: ForecastOutcomeResearchReport) -> None:
        row = self.to_row(report)
        placeholders = ", ".join(["%s"] * len(self.columns))
        sql = f"INSERT INTO {self.table_name} ({', '.join(self.columns)}) VALUES ({placeholders})"
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(row[column] for column in self.columns))


def rolling_validation_metrics(
    comparisons: Sequence[ForecastOutcomeComparison],
    *,
    as_of: datetime,
    bins: int = 10,
) -> dict[int, RollingValidationMetrics]:
    timestamp = normalize_timestamp(as_of)
    metrics: dict[int, RollingValidationMetrics] = {}
    for months in ROLLING_WINDOWS_MONTHS:
        start = timestamp - timedelta(days=months * 30)
        window = [
            comparison
            for comparison in comparisons
            if start <= comparison.resolved_timestamp <= timestamp
        ]
        metrics[months] = classification_metrics(window, window_months=months, bins=bins)
    return metrics


def classification_metrics(
    comparisons: Sequence[ForecastOutcomeComparison],
    *,
    window_months: int,
    bins: int = 10,
) -> RollingValidationMetrics:
    probabilities = [comparison.probability for comparison in comparisons]
    outcomes = [comparison.realized_outcome for comparison in comparisons]
    predictions = [comparison.predicted_outcome for comparison in comparisons]
    tp = sum(1 for pred, outcome in zip(predictions, outcomes) if pred == 1 and outcome == 1)
    fp = sum(1 for pred, outcome in zip(predictions, outcomes) if pred == 1 and outcome == 0)
    fn = sum(1 for pred, outcome in zip(predictions, outcomes) if pred == 0 and outcome == 1)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return RollingValidationMetrics(
        window_months=window_months,
        sample_count=len(comparisons),
        brier_score=brier_score(probabilities, outcomes),
        precision=round(precision, 10),
        recall=round(recall, 10),
        f1=round(f1, 10),
        roc_auc=roc_auc(probabilities, outcomes),
        calibration_error=expected_calibration_error(probabilities, outcomes, bins=bins),
    )


def roc_auc(probabilities: Sequence[float], outcomes: Sequence[int]) -> float | None:
    positives = [probability for probability, outcome in zip(probabilities, outcomes) if outcome == 1]
    negatives = [probability for probability, outcome in zip(probabilities, outcomes) if outcome == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    total = 0.0
    for positive in positives:
        for negative in negatives:
            total += 1.0
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return round(wins / total, 10) if total else None


def reliability_trend(rolling: Mapping[int, RollingValidationMetrics]) -> ReliabilityTrend:
    short = reliability_from_metrics(rolling.get(3))
    medium = reliability_from_metrics(rolling.get(6))
    long = reliability_from_metrics(rolling.get(12))
    slope = round(short - long, 10)
    if slope > 5.0:
        direction = "IMPROVING"
    elif slope < -5.0:
        direction = "DETERIORATING"
    else:
        direction = "STABLE"
    available = [score for score, metrics in ((short, rolling.get(3)), (medium, rolling.get(6)), (long, rolling.get(12))) if metrics and metrics.sample_count]
    reliability = mean(available) if available else 50.0
    return ReliabilityTrend(
        direction=direction,
        reliability_score=round(clamp(reliability, 0.0, 100.0), 6),
        short_term_score=round(short, 6),
        long_term_score=round(long, 6),
        slope=slope,
    )


def reliability_from_metrics(metrics: RollingValidationMetrics | None) -> float:
    if metrics is None or metrics.sample_count == 0:
        return 50.0
    auc_component = 50.0 if metrics.roc_auc is None else metrics.roc_auc * 100.0
    error_component = (1.0 - clamp(metrics.brier_score, 0.0, 1.0)) * 100.0
    calibration_component = (1.0 - clamp(metrics.calibration_error, 0.0, 1.0)) * 100.0
    f1_component = metrics.f1 * 100.0
    return clamp(
        error_component * 0.35
        + calibration_component * 0.25
        + auc_component * 0.20
        + f1_component * 0.20,
        0.0,
        100.0,
    )


def driver_attribution(
    comparisons: Sequence[ForecastOutcomeComparison],
) -> tuple[list[DriverAttribution], list[DriverAttribution]]:
    correct = [comparison for comparison in comparisons if comparison.correct]
    incorrect = [comparison for comparison in comparisons if not comparison.correct]
    return summarize_driver_group(correct), summarize_driver_group(incorrect)


def summarize_driver_group(comparisons: Sequence[ForecastOutcomeComparison]) -> list[DriverAttribution]:
    factors = sorted({factor for comparison in comparisons for factor in comparison.factors})
    attributions: list[DriverAttribution] = []
    for factor in factors:
        values = [comparison.factors[factor] for comparison in comparisons if factor in comparison.factors]
        if not values:
            continue
        attributions.append(
            DriverAttribution(
                factor=factor,
                contribution_score=round(mean(abs(value) for value in values), 10),
                average_value=round(mean(values), 10),
                sample_count=len(values),
            )
        )
    return sorted(attributions, key=lambda item: (-item.contribution_score, item.factor))


def adaptive_weight_audit(
    comparisons: Sequence[ForecastOutcomeComparison],
) -> list[AdaptiveWeightRecommendation]:
    factors = sorted(
        {
            factor
            for comparison in comparisons
            for factor in set(comparison.factors) | set(comparison.production_weights)
        }
    )
    if not factors:
        return []
    evidence = {factor: factor_evidence_score(comparisons, factor) for factor in factors}
    recommended = normalize_scores(evidence)
    current = normalize_scores(
        {
            factor: mean(
                [
                    comparison.production_weights[factor]
                    for comparison in comparisons
                    if factor in comparison.production_weights
                ]
                or [recommended.get(factor, 0.0)]
            )
            for factor in factors
        }
    )
    return [
        AdaptiveWeightRecommendation(
            factor=factor,
            current_weight=round(current.get(factor, 0.0), 10),
            recommended_weight=round(recommended.get(factor, 0.0), 10),
            evidence_score=round(evidence.get(factor, 0.0), 10),
            recommended_delta=round(recommended.get(factor, 0.0) - current.get(factor, 0.0), 10),
        )
        for factor in sorted(factors, key=lambda name: (-recommended.get(name, 0.0), name))
    ]


def factor_evidence_score(comparisons: Sequence[ForecastOutcomeComparison], factor: str) -> float:
    numerator = 0.0
    denominator = 0.0
    for comparison in comparisons:
        exposure = abs(comparison.factors.get(factor, 0.0))
        if exposure == 0.0:
            continue
        accuracy = 1.0 - comparison.probability_error
        numerator += exposure * clamp(accuracy, 0.0, 1.0)
        denominator += exposure
    if denominator == 0.0:
        return 0.0
    return clamp(numerator / denominator, 0.0, 1.0)


def research_readiness_score(
    resolved_count: int,
    rolling: Mapping[int, RollingValidationMetrics],
) -> float:
    coverage = min(resolved_count / 36.0, 1.0) * 45.0
    window_depth = sum(1 for metrics in rolling.values() if metrics.sample_count > 0) / len(ROLLING_WINDOWS_MONTHS) * 25.0
    longest = rolling.get(12)
    calibration = (1.0 - clamp(longest.calibration_error if longest else 0.5, 0.0, 1.0)) * 30.0
    return round(clamp(coverage + window_depth + calibration, 0.0, 100.0), 6)


def model_trust_score(
    rolling: Mapping[int, RollingValidationMetrics],
    trend: ReliabilityTrend,
) -> float:
    longest = rolling.get(12)
    if longest is None or longest.sample_count == 0:
        return round(clamp(trend.reliability_score * 0.5, 0.0, 100.0), 6)
    auc_component = 50.0 if longest.roc_auc is None else longest.roc_auc * 100.0
    score = (
        trend.reliability_score * 0.35
        + (1.0 - clamp(longest.brier_score, 0.0, 1.0)) * 100.0 * 0.30
        + (1.0 - clamp(longest.calibration_error, 0.0, 1.0)) * 100.0 * 0.20
        + auc_component * 0.15
    )
    return round(clamp(score, 0.0, 100.0), 6)


def report_to_dict(report: ForecastOutcomeResearchReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["generated_at"] = normalize_timestamp(report.generated_at).isoformat()
    return payload


def severity_for_report(report: ForecastOutcomeResearchReport) -> str:
    if report.model_trust_score < 45.0 or report.forecast_reliability_score < 45.0:
        return "CRITICAL"
    if report.model_trust_score < 65.0 or report.forecast_reliability_score < 65.0:
        return "MEDIUM"
    return "LOW"


def normalize_scores(scores: Mapping[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(value)) for value in scores.values())
    if total == 0.0:
        if not scores:
            return {}
        equal = 1.0 / len(scores)
        return {name: equal for name in scores}
    return {name: max(0.0, float(value)) / total for name, value in scores.items()}


def clean_factor_map(values: Mapping[str, float | int | None] | None) -> dict[str, float]:
    return {key: safe_float(value) for key, value in (values or {}).items() if safe_float(value) is not None}


def clean_weight_map(values: Mapping[str, float | int | None] | None) -> dict[str, float]:
    cleaned = {key: safe_float(value) for key, value in (values or {}).items() if safe_float(value) is not None}
    return normalize_scores(cleaned)


def safe_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if math.isnan(parsed):
        return None
    return parsed


def safe_outcome(value: int | bool | None) -> int:
    return 1 if bool(value) else 0
