from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from analytics.validation.exception_logger import (
    FailureAction,
    StructuredValidationExceptionLogger,
    ValidationFailure,
    ValidationRule,
    ValidationSeverity,
)


FRESHNESS_MAX_AGE_RULE = ValidationRule(
    rule_name="FRESHNESS_MAX_AGE",
    description="Record timestamps should be no older than the configured maximum age.",
    threshold="age_seconds <= max_age_seconds",
    severity=ValidationSeverity.WARNING,
    failure_action=FailureAction.FLAG_RECORD,
)

FRESHNESS_TIMESTAMP_PARSE_RULE = ValidationRule(
    rule_name="FRESHNESS_TIMESTAMP_PARSE",
    description="Freshness validation requires a parseable timestamp value.",
    threshold="timestamp is parseable",
    severity=ValidationSeverity.CRITICAL,
    failure_action=FailureAction.FLAG_RECORD,
)

FRESHNESS_VALIDATION_RULES = (
    FRESHNESS_MAX_AGE_RULE,
    FRESHNESS_TIMESTAMP_PARSE_RULE,
)


@dataclass(frozen=True)
class FreshnessValidationResult:
    records: list[dict[str, Any]]
    failures: list[ValidationFailure]
    stale_record_indexes: list[int]
    newest_timestamp: datetime | None


class FreshnessValidator:
    rules = FRESHNESS_VALIDATION_RULES

    def __init__(
        self,
        *,
        max_age_seconds: int,
        logger: StructuredValidationExceptionLogger | None = None,
    ) -> None:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative")
        self.max_age_seconds = max_age_seconds
        self.logger = logger or StructuredValidationExceptionLogger()

    def validate(
        self,
        *,
        source_name: str,
        records: Sequence[Mapping[str, Any]],
        timestamp_field: str = "timestamp",
        as_of: datetime | None = None,
    ) -> FreshnessValidationResult:
        materialized = [dict(record) for record in records]
        failures: list[ValidationFailure] = []
        stale_indexes: set[int] = set()
        parsed_timestamps: list[datetime] = []
        reference_time = self._normalize_timestamp(as_of or datetime.now(timezone.utc))

        for index, record in enumerate(materialized):
            raw_timestamp = record.get(timestamp_field)
            try:
                timestamp = self._normalize_timestamp(raw_timestamp)
            except (TypeError, ValueError) as exc:
                failures.append(
                    self.logger.build_failure(
                        source_name=source_name,
                        field_name=timestamp_field,
                        rule=FRESHNESS_TIMESTAMP_PARSE_RULE,
                        bad_value_raw=raw_timestamp,
                        message=str(exc),
                        record_index=index,
                    )
                )
                stale_indexes.add(index)
                continue

            parsed_timestamps.append(timestamp)
            age_seconds = max(0, int((reference_time - timestamp).total_seconds()))
            if age_seconds > self.max_age_seconds:
                stale_indexes.add(index)
                failures.append(
                    self.logger.build_failure(
                        source_name=source_name,
                        field_name=timestamp_field,
                        rule=FRESHNESS_MAX_AGE_RULE,
                        bad_value_raw=raw_timestamp,
                        message=f"Record age {age_seconds}s exceeds {self.max_age_seconds}s.",
                        record_index=index,
                    )
                )

        self.logger.log_many(failures)
        return FreshnessValidationResult(
            records=materialized,
            failures=failures,
            stale_record_indexes=sorted(stale_indexes),
            newest_timestamp=max(parsed_timestamps) if parsed_timestamps else None,
        )

    @staticmethod
    def _normalize_timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            raw = float(value)
            parsed = datetime.fromtimestamp(raw / 1000 if raw > 10_000_000_000 else raw, timezone.utc)
        elif isinstance(value, str):
            cleaned = value.strip()
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            parsed = datetime.fromisoformat(cleaned)
        else:
            raise ValueError(f"Invalid timestamp type: {type(value).__name__}")

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
