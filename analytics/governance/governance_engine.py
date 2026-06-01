from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any, Mapping, Protocol, Sequence

from analytics.common import clamp, normalize_timestamp

try:
    from scipy.optimize import minimize
except Exception:  # pragma: no cover - exercised only when scipy is absent.
    minimize = None


@dataclass(frozen=True)
class GovernanceConfig:
    psi_warning_threshold: float = 0.10
    psi_critical_threshold: float = 0.25
    cycle_weight_cap: float = 0.10
    health_threshold: float = 70.0
    retraining_cooldown_days: int = 30
    bss_bad_days: int = 5


@dataclass(frozen=True)
class ModelErrorProfile:
    model_name: str
    brier_scores: Sequence[float | None]
    source_health_score: float | None = 100.0
    is_cycle_engine: bool = False


@dataclass(frozen=True)
class WeightAllocation:
    weights: dict[str, float]
    objective_value: float
    optimizer_success: bool


@dataclass(frozen=True)
class RetrainingDecision:
    timestamp: datetime
    psi: float
    bss_bad_streak: int
    lock_outputs: bool
    retraining_required: bool
    cooldown_active: bool
    reason: str


@dataclass(frozen=True)
class GovernanceRun:
    timestamp: datetime
    decision: RetrainingDecision
    allocation: WeightAllocation


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


class GovernancePersistenceAdapter:
    table_name = "data_quality_exceptions"
    columns = (
        "timestamp",
        "source_name",
        "field_name",
        "exception_type",
        "bad_value_raw",
        "severity",
    )

    def to_row(self, run: GovernanceRun) -> dict[str, Any]:
        payload = {
            "psi": run.decision.psi,
            "bss_bad_streak": run.decision.bss_bad_streak,
            "lock_outputs": run.decision.lock_outputs,
            "retraining_required": run.decision.retraining_required,
            "cooldown_active": run.decision.cooldown_active,
            "reason": run.decision.reason,
            "weights": run.allocation.weights,
            "objective_value": run.allocation.objective_value,
            "optimizer_success": run.allocation.optimizer_success,
        }
        return {
            "timestamp": normalize_timestamp(run.timestamp),
            "source_name": "governance_engine",
            "field_name": "ensemble_governance",
            "exception_type": "GOVERNANCE_RETRAINING_TRIGGER"
            if run.decision.retraining_required
            else "GOVERNANCE_WEIGHT_UPDATE",
            "bad_value_raw": json.dumps(payload, sort_keys=True),
            "severity": severity_for_decision(run.decision),
        }

    def persist(self, connection: DbConnection, run: GovernanceRun) -> None:
        row = self.to_row(run)
        placeholders = ", ".join(["%s"] * len(self.columns))
        sql = f"INSERT INTO {self.table_name} ({', '.join(self.columns)}) VALUES ({placeholders})"
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(row[column] for column in self.columns))


class GovernanceEngine:
    def __init__(self, *, config: GovernanceConfig | None = None) -> None:
        self.config = config or GovernanceConfig()

    def run(
        self,
        *,
        expected_feature_distribution: Sequence[float | None],
        actual_feature_distribution: Sequence[float | None],
        model_profiles: Sequence[ModelErrorProfile],
        brier_skill_history: Sequence[float | None],
        as_of: datetime | None = None,
        last_retraining_at: datetime | None = None,
    ) -> GovernanceRun:
        timestamp = normalize_timestamp(as_of or datetime.now(timezone.utc))
        psi = population_stability_index(expected_feature_distribution, actual_feature_distribution)
        decision = self.retraining_decision(
            psi=psi,
            brier_skill_history=brier_skill_history,
            as_of=timestamp,
            last_retraining_at=last_retraining_at,
        )
        allocation = self.optimize_weights(model_profiles)
        return GovernanceRun(timestamp=timestamp, decision=decision, allocation=allocation)

    def retraining_decision(
        self,
        *,
        psi: float,
        brier_skill_history: Sequence[float | None],
        as_of: datetime,
        last_retraining_at: datetime | None = None,
    ) -> RetrainingDecision:
        timestamp = normalize_timestamp(as_of)
        bad_streak = consecutive_bad_bss(brier_skill_history)
        critical_drift = psi >= self.config.psi_critical_threshold
        bss_failure = bad_streak >= self.config.bss_bad_days
        cooldown_active = is_cooldown_active(
            timestamp,
            last_retraining_at,
            cooldown_days=self.config.retraining_cooldown_days,
        )
        trigger = critical_drift or bss_failure
        retraining_required = trigger and not cooldown_active
        if cooldown_active and trigger:
            reason = "COOLDOWN_ACTIVE"
        elif critical_drift:
            reason = "PSI_CRITICAL"
        elif bss_failure:
            reason = "BSS_DETERIORATION"
        elif psi >= self.config.psi_warning_threshold:
            reason = "PSI_WARNING"
        else:
            reason = "NORMAL"
        return RetrainingDecision(
            timestamp=timestamp,
            psi=round(clamp(psi, 0.0, 10.0), 10),
            bss_bad_streak=bad_streak,
            lock_outputs=trigger,
            retraining_required=retraining_required,
            cooldown_active=cooldown_active,
            reason=reason,
        )

    def optimize_weights(self, model_profiles: Sequence[ModelErrorProfile]) -> WeightAllocation:
        profiles = list(model_profiles)
        if not profiles:
            return WeightAllocation(weights={}, objective_value=0.0, optimizer_success=True)
        base = inverse_error_weights(profiles)
        attenuated = apply_health_attenuation(
            base,
            profiles,
            health_threshold=self.config.health_threshold,
        )
        allocation = solve_constrained_weights(
            attenuated,
            profiles,
            cycle_weight_cap=self.config.cycle_weight_cap,
        )
        return allocation

    def persist_run(
        self,
        connection: DbConnection,
        run: GovernanceRun,
        *,
        adapter: GovernancePersistenceAdapter | None = None,
    ) -> None:
        (adapter or GovernancePersistenceAdapter()).persist(connection, run)


def population_stability_index(
    expected: Sequence[float | None],
    actual: Sequence[float | None],
    *,
    bins: int = 10,
) -> float:
    if bins <= 0:
        raise ValueError("bins must be positive")
    expected_clean = clean_series(expected)
    actual_clean = clean_series(actual)
    if not expected_clean or not actual_clean:
        return 0.0
    combined = expected_clean + actual_clean
    low = min(combined)
    high = max(combined)
    if high == low:
        return 0.0
    width = (high - low) / bins
    psi = 0.0
    epsilon = 1e-6
    for index in range(bins):
        lower = low + index * width
        upper = high if index == bins - 1 else lower + width
        expected_share = bucket_share(expected_clean, lower, upper, include_upper=index == bins - 1)
        actual_share = bucket_share(actual_clean, lower, upper, include_upper=index == bins - 1)
        expected_share = max(expected_share, epsilon)
        actual_share = max(actual_share, epsilon)
        psi += (actual_share - expected_share) * math.log(actual_share / expected_share)
    return round(clamp(psi, 0.0, 10.0), 10)


def consecutive_bad_bss(brier_skill_history: Sequence[float | None]) -> int:
    streak = 0
    for value in reversed(list(brier_skill_history)):
        if value is not None and float(value) < 0.0:
            streak += 1
            continue
        break
    return streak


def is_cooldown_active(
    as_of: datetime,
    last_retraining_at: datetime | None,
    *,
    cooldown_days: int,
) -> bool:
    if last_retraining_at is None:
        return False
    if cooldown_days <= 0:
        return False
    elapsed = normalize_timestamp(as_of) - normalize_timestamp(last_retraining_at)
    return elapsed < timedelta(days=cooldown_days)


def inverse_error_weights(profiles: Sequence[ModelErrorProfile]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for profile in profiles:
        avg_error = mean_or_default([clamp_value(value, 0.0, 1.0) for value in profile.brier_scores], 0.25)
        variance = pstdev([clamp_value(value, 0.0, 1.0) for value in profile.brier_scores]) if profile.brier_scores else 0.0
        scores[profile.model_name] = 1.0 / max(avg_error + variance, 1e-6)
    return normalize_weights(scores)


def apply_health_attenuation(
    weights: Mapping[str, float],
    profiles: Sequence[ModelErrorProfile],
    *,
    health_threshold: float,
) -> dict[str, float]:
    adjusted = dict(weights)
    for profile in profiles:
        health = clamp_value(profile.source_health_score, 0.0, 100.0)
        if health < health_threshold:
            adjusted[profile.model_name] = adjusted.get(profile.model_name, 0.0) * (health / health_threshold)
    return normalize_weights(adjusted)


def solve_constrained_weights(
    initial_weights: Mapping[str, float],
    profiles: Sequence[ModelErrorProfile],
    *,
    cycle_weight_cap: float,
) -> WeightAllocation:
    names = [profile.model_name for profile in profiles]
    if not names:
        return WeightAllocation(weights={}, objective_value=0.0, optimizer_success=True)
    target = [initial_weights.get(name, 0.0) for name in names]
    target = normalize_vector(target)
    cycle_indexes = [index for index, profile in enumerate(profiles) if profile.is_cycle_engine]
    bounds = [
        (0.0, min(1.0, cycle_weight_cap) if index in cycle_indexes else 1.0)
        for index, _profile in enumerate(profiles)
    ]

    if minimize is not None:
        result = minimize(
            lambda vector: sum((float(value) - target[index]) ** 2 for index, value in enumerate(vector)),
            target,
            method="SLSQP",
            bounds=bounds,
            constraints=({"type": "eq", "fun": lambda vector: sum(vector) - 1.0},),
            options={"maxiter": 200, "ftol": 1e-12, "disp": False},
        )
        if bool(getattr(result, "success", False)):
            weights = enforce_constraints(
                [float(value) for value in result.x],
                cycle_indexes=cycle_indexes,
                cycle_weight_cap=cycle_weight_cap,
            )
            return WeightAllocation(
                weights=dict(zip(names, weights)),
                objective_value=round(objective(weights, target), 10),
                optimizer_success=True,
            )

    weights = enforce_constraints(
        target,
        cycle_indexes=cycle_indexes,
        cycle_weight_cap=cycle_weight_cap,
    )
    return WeightAllocation(
        weights=dict(zip(names, weights)),
        objective_value=round(objective(weights, target), 10),
        optimizer_success=False,
    )


def enforce_constraints(
    weights: Sequence[float],
    *,
    cycle_indexes: Sequence[int],
    cycle_weight_cap: float,
) -> list[float]:
    constrained = [max(0.0, float(value)) for value in weights]
    surplus = 0.0
    for index in cycle_indexes:
        if constrained[index] > cycle_weight_cap:
            surplus += constrained[index] - cycle_weight_cap
            constrained[index] = cycle_weight_cap
    recipient_indexes = [index for index in range(len(constrained)) if index not in cycle_indexes]
    recipient_total = sum(constrained[index] for index in recipient_indexes)
    if surplus > 0.0 and recipient_indexes:
        if recipient_total == 0.0:
            increment = surplus / len(recipient_indexes)
            for index in recipient_indexes:
                constrained[index] += increment
        else:
            for index in recipient_indexes:
                constrained[index] += surplus * constrained[index] / recipient_total
    total = sum(constrained)
    if total == 0.0:
        constrained = [1.0 / len(constrained) for _value in constrained]
    else:
        constrained = [value / total for value in constrained]
    for index in cycle_indexes:
        if constrained[index] > cycle_weight_cap:
            constrained[index] = cycle_weight_cap
    non_cycle = [index for index in range(len(constrained)) if index not in cycle_indexes]
    remaining = 1.0 - sum(constrained[index] for index in cycle_indexes)
    non_cycle_total = sum(constrained[index] for index in non_cycle)
    if non_cycle:
        if non_cycle_total == 0.0:
            for index in non_cycle:
                constrained[index] = remaining / len(non_cycle)
        else:
            for index in non_cycle:
                constrained[index] = remaining * constrained[index] / non_cycle_total
    rounded = [round(clamp(value, 0.0, 1.0), 10) for value in constrained]
    correction = round(1.0 - sum(rounded), 10)
    if rounded:
        target_index = non_cycle[0] if non_cycle else 0
        rounded[target_index] = round(clamp(rounded[target_index] + correction, 0.0, 1.0), 10)
    return rounded


def normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(value)) for value in weights.values())
    if total == 0.0:
        if not weights:
            return {}
        equal = 1.0 / len(weights)
        return {name: equal for name in weights}
    return {name: max(0.0, float(value)) / total for name, value in weights.items()}


def normalize_vector(values: Sequence[float]) -> list[float]:
    total = sum(max(0.0, float(value)) for value in values)
    if total == 0.0:
        return [1.0 / len(values) for _value in values] if values else []
    return [max(0.0, float(value)) / total for value in values]


def objective(weights: Sequence[float], target: Sequence[float]) -> float:
    return sum((float(weight) - float(target[index])) ** 2 for index, weight in enumerate(weights))


def bucket_share(values: Sequence[float], lower: float, upper: float, *, include_upper: bool) -> float:
    if include_upper:
        count = sum(1 for value in values if lower <= value <= upper)
    else:
        count = sum(1 for value in values if lower <= value < upper)
    return count / len(values) if values else 0.0


def clean_series(values: Sequence[float | None]) -> list[float]:
    clean: list[float] = []
    for value in values:
        if value is None:
            continue
        parsed = float(value)
        if math.isnan(parsed):
            continue
        clean.append(parsed)
    return clean


def clamp_value(value: float | None, lower: float, upper: float) -> float:
    if value is None:
        return (lower + upper) / 2.0
    parsed = float(value)
    if math.isnan(parsed):
        return (lower + upper) / 2.0
    return clamp(parsed, lower, upper)


def mean_or_default(values: Sequence[float], default: float) -> float:
    return mean(values) if values else default


def severity_for_decision(decision: RetrainingDecision) -> str:
    if decision.retraining_required:
        return "CRITICAL"
    if decision.lock_outputs or decision.reason == "PSI_WARNING":
        return "MEDIUM"
    return "LOW"
