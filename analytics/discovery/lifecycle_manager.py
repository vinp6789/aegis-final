from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from analytics.discovery.discovery_engine import FeatureEvaluation


class FeatureLifecycleState(str, Enum):
    PROPOSED = "PROPOSED"
    WATCH = "WATCH"
    PROMOTED = "PROMOTED"
    DEMOTED = "DEMOTED"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class FeatureLifecycleRecord:
    feature_name: str
    current_state: FeatureLifecycleState
    target_scope: str
    primary_horizon_months: int
    secondary_horizon_months: int
    current_score: float
    peak_score: float
    last_evaluated: datetime
    consecutive_monthly_failures: int = 0
    demoted_at: datetime | None = None
    retirement_reason: str | None = None


@dataclass(frozen=True)
class LifecycleDecision:
    record: FeatureLifecycleRecord
    previous_state: FeatureLifecycleState | None
    reason: str


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


@dataclass(frozen=True)
class LifecycleThresholds:
    watch_score: float = 45.0
    promotion_score: float = 70.0
    demotion_score: float = 50.0
    retirement_score: float = 25.0
    max_consecutive_failures: int = 3
    granger_p_threshold: float = 0.05
    transfer_entropy_threshold: float = 0.02


class LifecycleManager:
    def __init__(self, thresholds: LifecycleThresholds | None = None) -> None:
        self.thresholds = thresholds or LifecycleThresholds()

    def decide(
        self,
        evaluation: FeatureEvaluation,
        existing: FeatureLifecycleRecord | None = None,
    ) -> LifecycleDecision:
        previous_state = existing.current_state if existing else None
        peak_score = max(existing.peak_score if existing else 0.0, evaluation.peak_score)
        failures = existing.consecutive_monthly_failures if existing else 0
        demoted_at = existing.demoted_at if existing else None
        retirement_reason = existing.retirement_reason if existing else None

        if evaluation.deterioration_detected or evaluation.current_score < self.thresholds.demotion_score:
            failures += 1
        else:
            failures = 0

        state, reason = self._next_state(
            evaluation=evaluation,
            current_score=evaluation.current_score,
            failures=failures,
            previous_state=previous_state,
        )

        if state is FeatureLifecycleState.DEMOTED and previous_state is not FeatureLifecycleState.DEMOTED:
            demoted_at = evaluation.evaluated_at
        if state is FeatureLifecycleState.RETIRED and not retirement_reason:
            retirement_reason = reason

        record = FeatureLifecycleRecord(
            feature_name=evaluation.feature_name,
            current_state=state,
            target_scope=evaluation.target_scope,
            primary_horizon_months=evaluation.primary_horizon_months,
            secondary_horizon_months=evaluation.secondary_horizon_months,
            current_score=round(evaluation.current_score, 2),
            peak_score=round(peak_score, 2),
            last_evaluated=evaluation.evaluated_at.astimezone(timezone.utc),
            consecutive_monthly_failures=failures,
            demoted_at=demoted_at.astimezone(timezone.utc) if demoted_at else None,
            retirement_reason=retirement_reason,
        )
        return LifecycleDecision(record=record, previous_state=previous_state, reason=reason)

    def decide_many(
        self,
        evaluations: list[FeatureEvaluation],
        existing_records: dict[str, FeatureLifecycleRecord] | None = None,
    ) -> list[LifecycleDecision]:
        existing_records = existing_records or {}
        return [
            self.decide(evaluation, existing_records.get(evaluation.feature_name))
            for evaluation in evaluations
        ]

    def persist_decision(self, connection: DbConnection, decision: LifecycleDecision) -> None:
        record = decision.record
        sql = """
            INSERT INTO feature_lifecycle_registry (
                feature_name,
                current_state,
                target_scope,
                primary_horizon_months,
                secondary_horizon_months,
                current_score,
                peak_score,
                last_evaluated,
                consecutive_monthly_failures,
                demoted_at,
                retirement_reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (feature_name) DO UPDATE SET
                current_state = EXCLUDED.current_state,
                target_scope = EXCLUDED.target_scope,
                primary_horizon_months = EXCLUDED.primary_horizon_months,
                secondary_horizon_months = EXCLUDED.secondary_horizon_months,
                current_score = EXCLUDED.current_score,
                peak_score = GREATEST(feature_lifecycle_registry.peak_score, EXCLUDED.peak_score),
                last_evaluated = EXCLUDED.last_evaluated,
                consecutive_monthly_failures = EXCLUDED.consecutive_monthly_failures,
                demoted_at = EXCLUDED.demoted_at,
                retirement_reason = EXCLUDED.retirement_reason
        """
        values = (
            record.feature_name,
            record.current_state.value,
            record.target_scope,
            record.primary_horizon_months,
            record.secondary_horizon_months,
            record.current_score,
            record.peak_score,
            record.last_evaluated,
            record.consecutive_monthly_failures,
            record.demoted_at,
            record.retirement_reason,
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, values)

    def persist_decisions(self, connection: DbConnection, decisions: list[LifecycleDecision]) -> None:
        for decision in decisions:
            self.persist_decision(connection, decision)

    def _next_state(
        self,
        *,
        evaluation: FeatureEvaluation,
        current_score: float,
        failures: int,
        previous_state: FeatureLifecycleState | None,
    ) -> tuple[FeatureLifecycleState, str]:
        if failures >= self.thresholds.max_consecutive_failures:
            return FeatureLifecycleState.RETIRED, "maximum consecutive monthly failures reached"

        if previous_state is FeatureLifecycleState.PROMOTED:
            if evaluation.deterioration_detected or current_score < self.thresholds.demotion_score:
                return FeatureLifecycleState.DEMOTED, "promoted feature deterioration detected"
            return FeatureLifecycleState.PROMOTED, "promoted feature remains healthy"

        if previous_state is FeatureLifecycleState.WATCH and evaluation.out_of_sample_validated:
            return FeatureLifecycleState.PROMOTED, "watch feature passed out-of-sample validation"

        granger_p = evaluation.granger_p_value
        transfer_entropy = evaluation.transfer_entropy_value
        if (
            granger_p is not None
            and transfer_entropy is not None
            and granger_p < self.thresholds.granger_p_threshold
            and transfer_entropy > self.thresholds.transfer_entropy_threshold
        ):
            return FeatureLifecycleState.WATCH, "Granger p-value and transfer entropy meet watch thresholds"

        if current_score < self.thresholds.retirement_score and previous_state is FeatureLifecycleState.DEMOTED:
            return FeatureLifecycleState.RETIRED, "demoted feature score fell below retirement threshold"

        if granger_p is None and transfer_entropy is None:
            if current_score >= self.thresholds.promotion_score:
                return FeatureLifecycleState.PROMOTED, "legacy score meets promotion threshold"
            if current_score >= self.thresholds.watch_score:
                return FeatureLifecycleState.WATCH, "legacy score meets watch threshold"

        return FeatureLifecycleState.PROPOSED, "score remains below watch threshold"
