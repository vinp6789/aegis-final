from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from analytics.validation.exception_logger import (
    FailureAction,
    StructuredValidationExceptionLogger,
    ValidationFailure,
    ValidationRule,
    ValidationSeverity,
)


QUALITY_SCORE_MINIMUM_RULE = ValidationRule(
    rule_name="QUALITY_SCORE_MINIMUM",
    description="Overall validation quality score should remain above the configured minimum.",
    threshold="quality_score >= minimum_quality_score",
    severity=ValidationSeverity.WARNING,
    failure_action=FailureAction.LOG_ONLY,
)

QUALITY_CRITICAL_FAILURE_RULE = ValidationRule(
    rule_name="QUALITY_CRITICAL_FAILURE_RATIO",
    description="Critical validation failures should not exceed the configured record ratio.",
    threshold="critical_failures / total_records <= max_critical_failure_ratio",
    severity=ValidationSeverity.CRITICAL,
    failure_action=FailureAction.BLOCK_BATCH,
)

QUALITY_SCORING_RULES = (
    QUALITY_SCORE_MINIMUM_RULE,
    QUALITY_CRITICAL_FAILURE_RULE,
)


@dataclass(frozen=True)
class QualityScoreResult:
    source_name: str
    total_records: int
    score: float
    failure_count: int
    critical_failure_count: int
    warning_failure_count: int
    info_failure_count: int
    blocked: bool
    failures: list[ValidationFailure]


class QualityScorer:
    rules = QUALITY_SCORING_RULES

    def __init__(
        self,
        *,
        minimum_quality_score: float = 80.0,
        max_critical_failure_ratio: float = 0.0,
        logger: StructuredValidationExceptionLogger | None = None,
    ) -> None:
        if not 0.0 <= minimum_quality_score <= 100.0:
            raise ValueError("minimum_quality_score must be between 0 and 100")
        if not 0.0 <= max_critical_failure_ratio <= 1.0:
            raise ValueError("max_critical_failure_ratio must be between 0 and 1")
        self.minimum_quality_score = minimum_quality_score
        self.max_critical_failure_ratio = max_critical_failure_ratio
        self.logger = logger or StructuredValidationExceptionLogger()

    def score(
        self,
        *,
        source_name: str,
        total_records: int,
        validation_failures: Sequence[ValidationFailure],
    ) -> QualityScoreResult:
        if total_records < 0:
            raise ValueError("total_records must be non-negative")

        critical_count = sum(
            1 for failure in validation_failures if failure.rule.severity.value == "CRITICAL"
        )
        warning_count = sum(
            1 for failure in validation_failures if failure.rule.severity.value == "WARNING"
        )
        info_count = sum(
            1 for failure in validation_failures if failure.rule.severity.value == "INFO"
        )
        denominator = max(total_records, 1)
        score_value = round(
            max(
                0.0,
                100.0
                - (critical_count / denominator) * 70.0
                - (warning_count / denominator) * 25.0
                - (info_count / denominator) * 5.0,
            ),
            2,
        )

        generated_failures: list[ValidationFailure] = []
        critical_ratio = critical_count / denominator
        if critical_ratio > self.max_critical_failure_ratio:
            generated_failures.append(
                self.logger.build_failure(
                    source_name=source_name,
                    field_name="__batch__",
                    rule=QUALITY_CRITICAL_FAILURE_RULE,
                    bad_value_raw=critical_ratio,
                    message=(
                        f"Critical failure ratio {critical_ratio:.4f} exceeds "
                        f"{self.max_critical_failure_ratio:.4f}."
                    ),
                )
            )
        if score_value < self.minimum_quality_score:
            generated_failures.append(
                self.logger.build_failure(
                    source_name=source_name,
                    field_name="__batch__",
                    rule=QUALITY_SCORE_MINIMUM_RULE,
                    bad_value_raw=score_value,
                    message=f"Quality score {score_value:.2f} is below {self.minimum_quality_score:.2f}.",
                )
            )

        self.logger.log_many(generated_failures)
        return QualityScoreResult(
            source_name=source_name,
            total_records=total_records,
            score=score_value,
            failure_count=len(validation_failures) + len(generated_failures),
            critical_failure_count=critical_count,
            warning_failure_count=warning_count,
            info_failure_count=info_count,
            blocked=bool(
                generated_failures
                and any(failure.rule.failure_action is FailureAction.BLOCK_BATCH for failure in generated_failures)
            ),
            failures=generated_failures,
        )
