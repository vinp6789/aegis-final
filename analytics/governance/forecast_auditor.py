from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Iterable, Mapping, Protocol, Sequence

from analytics.common import clamp, clip_probability, normalize_timestamp


@dataclass(frozen=True)
class ForecastRecord:
    timestamp: datetime
    target_scope: str
    forecast_type: str
    horizon_months: int
    probability: float | None
    realized_outcome: int | bool | None = None
    resolved_timestamp: datetime | None = None


@dataclass(frozen=True)
class ForecastAuditMetrics:
    brier_score: float
    brier_skill_score: float
    expected_calibration_error: float
    drift_7d: float
    drift_30d: float
    drift_90d: float
    resolved_count: int
    unresolved_count: int
    calibration_drift_detected: bool


@dataclass(frozen=True)
class ForecastAuditResult:
    audit_timestamp: datetime
    target_scope: str
    forecast_type: str
    horizon_months: int
    metrics: ForecastAuditMetrics


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


class ForecastAuditRepository(Protocol):
    def persist(self, connection: DbConnection, result: ForecastAuditResult) -> None:
        ...


class ForecastAuditor:
    def __init__(
        self,
        *,
        bins: int = 10,
        drift_threshold: float = 0.15,
        brier_threshold: float = 0.18,
    ) -> None:
        if bins <= 0:
            raise ValueError("bins must be positive")
        if drift_threshold < 0.0 or brier_threshold < 0.0:
            raise ValueError("thresholds must be non-negative")
        self.bins = bins
        self.drift_threshold = drift_threshold
        self.brier_threshold = brier_threshold

    def audit(
        self,
        records: Sequence[ForecastRecord],
        *,
        target_scope: str = "GLOBAL",
        forecast_type: str = "systemic_stress",
        horizon_months: int = 12,
    ) -> ForecastAuditResult:
        selected = [
            record
            for record in records
            if record.target_scope == target_scope
            and record.forecast_type == forecast_type
            and record.horizon_months == horizon_months
        ]
        resolved = [record for record in selected if record.realized_outcome is not None]
        probabilities = [safe_probability(record.probability) for record in resolved]
        outcomes = [safe_outcome(record.realized_outcome) for record in resolved]
        brier = brier_score(probabilities, outcomes)
        baseline = baseline_brier_score(outcomes)
        bss = brier_skill_score(brier, baseline)
        ece = expected_calibration_error(probabilities, outcomes, bins=self.bins)
        drift = {
            7: forecast_drift(selected, days=7),
            30: forecast_drift(selected, days=30),
            90: forecast_drift(selected, days=90),
        }
        drift_detected = (
            brier > self.brier_threshold
            or ece > self.drift_threshold
            or any(value > self.drift_threshold for value in drift.values())
        )
        return ForecastAuditResult(
            audit_timestamp=datetime.now(timezone.utc),
            target_scope=target_scope,
            forecast_type=forecast_type,
            horizon_months=horizon_months,
            metrics=ForecastAuditMetrics(
                brier_score=brier,
                brier_skill_score=bss,
                expected_calibration_error=ece,
                drift_7d=drift[7],
                drift_30d=drift[30],
                drift_90d=drift[90],
                resolved_count=len(resolved),
                unresolved_count=len(selected) - len(resolved),
                calibration_drift_detected=drift_detected,
            ),
        )

    def audit_and_persist(
        self,
        connection: DbConnection,
        records: Sequence[ForecastRecord],
        *,
        repository: ForecastAuditRepository,
        target_scope: str = "GLOBAL",
        forecast_type: str = "systemic_stress",
        horizon_months: int = 12,
    ) -> ForecastAuditResult:
        result = self.audit(
            records,
            target_scope=target_scope,
            forecast_type=forecast_type,
            horizon_months=horizon_months,
        )
        repository.persist(connection, result)
        return result

    def map_realizations(
        self,
        predictions: Sequence[ForecastRecord],
        realizations: Mapping[datetime, int | bool],
    ) -> list[ForecastRecord]:
        mapped: list[ForecastRecord] = []
        normalized_realizations = {
            normalize_timestamp(timestamp): safe_outcome(outcome)
            for timestamp, outcome in realizations.items()
        }
        for prediction in predictions:
            resolved_at = normalize_timestamp(prediction.resolved_timestamp or prediction.timestamp)
            outcome = normalized_realizations.get(resolved_at, prediction.realized_outcome)
            mapped.append(
                ForecastRecord(
                    timestamp=normalize_timestamp(prediction.timestamp),
                    target_scope=prediction.target_scope,
                    forecast_type=prediction.forecast_type,
                    horizon_months=prediction.horizon_months,
                    probability=prediction.probability,
                    realized_outcome=outcome,
                    resolved_timestamp=resolved_at,
                )
            )
        return mapped


class ForecastAuditExceptionPersistenceAdapter:
    table_name = "data_quality_exceptions"
    columns = (
        "timestamp",
        "source_name",
        "field_name",
        "exception_type",
        "bad_value_raw",
        "severity",
    )

    def to_row(self, result: ForecastAuditResult) -> dict[str, Any]:
        payload = {
            "target_scope": result.target_scope,
            "forecast_type": result.forecast_type,
            "horizon_months": result.horizon_months,
            "metrics": {
                "brier_score": result.metrics.brier_score,
                "brier_skill_score": result.metrics.brier_skill_score,
                "expected_calibration_error": result.metrics.expected_calibration_error,
                "drift_7d": result.metrics.drift_7d,
                "drift_30d": result.metrics.drift_30d,
                "drift_90d": result.metrics.drift_90d,
                "resolved_count": result.metrics.resolved_count,
                "unresolved_count": result.metrics.unresolved_count,
                "calibration_drift_detected": result.metrics.calibration_drift_detected,
            },
        }
        return {
            "timestamp": normalize_timestamp(result.audit_timestamp),
            "source_name": "forecast_auditor",
            "field_name": result.forecast_type,
            "exception_type": "FORECAST_CALIBRATION_DRIFT"
            if result.metrics.calibration_drift_detected
            else "FORECAST_AUDIT_METRICS",
            "bad_value_raw": json.dumps(payload, sort_keys=True),
            "severity": severity_for_result(result),
        }

    def persist(self, connection: DbConnection, result: ForecastAuditResult) -> None:
        row = self.to_row(result)
        placeholders = ", ".join(["%s"] * len(self.columns))
        sql = f"INSERT INTO {self.table_name} ({', '.join(self.columns)}) VALUES ({placeholders})"
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(row[column] for column in self.columns))


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    pairs = aligned_pairs(probabilities, outcomes)
    if not pairs:
        return 0.0
    return round(mean((probability - outcome) ** 2 for probability, outcome in pairs), 10)


def baseline_brier_score(outcomes: Sequence[int]) -> float:
    clean = [safe_outcome(outcome) for outcome in outcomes]
    if not clean:
        return 0.0
    baseline = mean(clean)
    return round(mean((baseline - outcome) ** 2 for outcome in clean), 10)


def brier_skill_score(model_brier: float, baseline_brier: float) -> float:
    if baseline_brier == 0.0:
        return 1.0 if model_brier == 0.0 else -1.0
    return round(clamp(1.0 - model_brier / baseline_brier, -1.0, 1.0), 10)


def expected_calibration_error(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    bins: int = 10,
) -> float:
    if bins <= 0:
        raise ValueError("bins must be positive")
    pairs = aligned_pairs(probabilities, outcomes)
    if not pairs:
        return 0.0
    total = len(pairs)
    ece = 0.0
    for bin_index in range(bins):
        lower = bin_index / bins
        upper = (bin_index + 1) / bins
        if bin_index == bins - 1:
            members = [(prob, outcome) for prob, outcome in pairs if lower <= prob <= upper]
        else:
            members = [(prob, outcome) for prob, outcome in pairs if lower <= prob < upper]
        if not members:
            continue
        confidence = mean(probability for probability, _outcome in members)
        accuracy = mean(outcome for _probability, outcome in members)
        ece += len(members) / total * abs(confidence - accuracy)
    return round(clamp(ece, 0.0, 1.0), 10)


def forecast_drift(records: Sequence[ForecastRecord], *, days: int) -> float:
    if days <= 0:
        raise ValueError("days must be positive")
    clean = sorted(
        [
            (normalize_timestamp(record.timestamp), safe_probability(record.probability))
            for record in records
        ],
        key=lambda item: item[0],
    )
    if len(clean) < 2:
        return 0.0
    latest = clean[-1][0]
    recent_start = latest - timedelta(days=days)
    previous_start = latest - timedelta(days=days * 2)
    recent = [probability for timestamp, probability in clean if timestamp > recent_start]
    previous = [
        probability
        for timestamp, probability in clean
        if previous_start < timestamp <= recent_start
    ]
    if not recent or not previous:
        return 0.0
    return round(clamp(abs(mean(recent) - mean(previous)), 0.0, 1.0), 10)


def severity_for_result(result: ForecastAuditResult) -> str:
    metrics = result.metrics
    if metrics.brier_score > 0.25 or metrics.expected_calibration_error > 0.25 or metrics.drift_30d > 0.25:
        return "CRITICAL"
    if metrics.calibration_drift_detected:
        return "MEDIUM"
    return "LOW"


def aligned_pairs(probabilities: Sequence[float], outcomes: Sequence[int]) -> list[tuple[float, int]]:
    length = min(len(probabilities), len(outcomes))
    return [
        (safe_probability(probabilities[index]), safe_outcome(outcomes[index]))
        for index in range(length)
    ]


def safe_probability(value: float | int | None) -> float:
    return clip_probability(value, default=0.5)


def safe_outcome(value: int | bool | None) -> int:
    return 1 if bool(value) else 0


def records_from_probability_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    forecast_type: str = "systemic_stress",
    horizon_months: int = 12,
    target_column: str = "realized_outcome",
) -> list[ForecastRecord]:
    probability_column = probability_column_for(forecast_type, horizon_months)
    records: list[ForecastRecord] = []
    for row in rows:
        records.append(
            ForecastRecord(
                timestamp=normalize_timestamp(row.get("timestamp")),
                target_scope=str(row.get("target_scope", "GLOBAL")),
                forecast_type=forecast_type,
                horizon_months=horizon_months,
                probability=row.get(probability_column),
                realized_outcome=row.get(target_column),
                resolved_timestamp=normalize_timestamp(row.get("resolved_timestamp") or row.get("timestamp")),
            )
        )
    return records


def probability_column_for(forecast_type: str, horizon_months: int) -> str:
    horizon = int(horizon_months)
    if forecast_type == "crypto_risk_off":
        return f"pump_prob_{horizon}m"
    if forecast_type in {"market_crash", "systemic_stress", "liquidity_contraction", "sector_stress"}:
        return f"crash_prob_{horizon}m"
    raise ValueError(f"Unsupported forecast type: {forecast_type}")
