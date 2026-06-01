from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence

from analytics.validation.exception_logger import (
    FailureAction,
    StructuredValidationExceptionLogger,
    ValidationFailure,
    ValidationRule,
    ValidationSeverity,
)


OUTLIER_ZSCORE_RULE = ValidationRule(
    rule_name="OUTLIER_ZSCORE",
    description="Numeric observations should not exceed the configured absolute z-score threshold.",
    threshold="absolute z-score <= 3.5",
    severity=ValidationSeverity.WARNING,
    failure_action=FailureAction.FLAG_RECORD,
)

OUTLIER_DETECTION_RULES = (OUTLIER_ZSCORE_RULE,)


@dataclass(frozen=True)
class OutlierDetectionResult:
    records: list[dict[str, Any]]
    failures: list[ValidationFailure]
    flagged_record_indexes: list[int]


class OutlierDetector:
    rules = OUTLIER_DETECTION_RULES

    def __init__(
        self,
        *,
        zscore_threshold: float = 3.5,
        logger: StructuredValidationExceptionLogger | None = None,
    ) -> None:
        if zscore_threshold <= 0.0:
            raise ValueError("zscore_threshold must be positive")
        self.zscore_threshold = zscore_threshold
        self.logger = logger or StructuredValidationExceptionLogger()

    def detect(
        self,
        *,
        source_name: str,
        records: Sequence[Mapping[str, Any]],
        numeric_fields: Sequence[str],
    ) -> OutlierDetectionResult:
        materialized = [dict(record) for record in records]
        failures: list[ValidationFailure] = []
        flagged_indexes: set[int] = set()

        for field_name in numeric_fields:
            indexed_values: list[tuple[int, float]] = []
            for index, record in enumerate(materialized):
                value = record.get(field_name)
                if value is None or value == "":
                    continue
                try:
                    indexed_values.append((index, float(value)))
                except (TypeError, ValueError):
                    continue

            values = [value for _index, value in indexed_values]
            if len(values) < 3:
                continue
            avg = mean(values)
            deviation = pstdev(values)
            if deviation == 0.0:
                continue

            for index, value in indexed_values:
                zscore = abs((value - avg) / deviation)
                if zscore > self.zscore_threshold:
                    flagged_indexes.add(index)
                    failures.append(
                        self.logger.build_failure(
                            source_name=source_name,
                            field_name=field_name,
                            rule=OUTLIER_ZSCORE_RULE,
                            bad_value_raw=value,
                            message=f"Z-score {zscore:.4f} exceeds {self.zscore_threshold}.",
                            record_index=index,
                        )
                    )

        self.logger.log_many(failures)
        return OutlierDetectionResult(
            records=materialized,
            failures=failures,
            flagged_record_indexes=sorted(flagged_indexes),
        )
