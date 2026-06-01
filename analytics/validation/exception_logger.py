from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Protocol


class ValidationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class FailureAction(str, Enum):
    LOG_ONLY = "LOG_ONLY"
    FLAG_RECORD = "FLAG_RECORD"
    BLOCK_BATCH = "BLOCK_BATCH"


@dataclass(frozen=True)
class ValidationRule:
    rule_name: str
    description: str
    threshold: str
    severity: ValidationSeverity
    failure_action: FailureAction


@dataclass(frozen=True)
class ValidationFailure:
    timestamp: datetime
    source_name: str
    field_name: str
    rule: ValidationRule
    bad_value_raw: str | None
    message: str
    record_index: int | None = None

    def to_exception_row(self) -> dict[str, Any]:
        payload = {
            "rule_name": self.rule.rule_name,
            "description": self.rule.description,
            "threshold": self.rule.threshold,
            "severity": self.rule.severity.value,
            "failure_action": self.rule.failure_action.value,
            "message": self.message,
            "record_index": self.record_index,
            "bad_value_raw": self.bad_value_raw,
        }
        return {
            "timestamp": self.timestamp.astimezone(timezone.utc),
            "source_name": self.source_name,
            "field_name": self.field_name,
            "exception_type": self.rule.rule_name,
            "bad_value_raw": json.dumps(payload, sort_keys=True),
            "severity": self.db_severity,
        }

    @property
    def db_severity(self) -> str:
        if self.rule.severity is ValidationSeverity.CRITICAL:
            return "CRITICAL"
        if self.rule.severity is ValidationSeverity.WARNING:
            return "MEDIUM"
        return "LOW"

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["timestamp"] = self.timestamp.astimezone(timezone.utc).isoformat()
        record["rule"] = asdict(self.rule)
        return record


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


class StructuredValidationExceptionLogger:
    """Structured validation logger backed by data_quality_exceptions."""

    table_name = "data_quality_exceptions"
    columns = (
        "timestamp",
        "source_name",
        "field_name",
        "exception_type",
        "bad_value_raw",
        "severity",
    )

    def __init__(self) -> None:
        self.records: list[ValidationFailure] = []

    def build_failure(
        self,
        *,
        source_name: str,
        field_name: str,
        rule: ValidationRule,
        bad_value_raw: Any,
        message: str,
        record_index: int | None = None,
    ) -> ValidationFailure:
        return ValidationFailure(
            timestamp=datetime.now(timezone.utc),
            source_name=source_name,
            field_name=field_name,
            rule=rule,
            bad_value_raw=None if bad_value_raw is None else str(bad_value_raw),
            message=message,
            record_index=record_index,
        )

    def log_failure(self, failure: ValidationFailure) -> ValidationFailure:
        self.records.append(failure)
        return failure

    def log_many(self, failures: Iterable[ValidationFailure]) -> None:
        self.records.extend(failures)

    def persist_failure(self, connection: DbConnection, failure: ValidationFailure) -> None:
        self.persist_failures(connection, [failure])

    def persist_failures(
        self,
        connection: DbConnection,
        failures: Iterable[ValidationFailure] | None = None,
    ) -> None:
        rows = [failure.to_exception_row() for failure in (failures if failures is not None else self.records)]
        if not rows:
            return
        placeholders = ", ".join(["%s"] * len(self.columns))
        column_sql = ", ".join(self.columns)
        sql = f"INSERT INTO {self.table_name} ({column_sql}) VALUES ({placeholders})"
        with connection.cursor() as cursor:
            for row in rows:
                cursor.execute(sql, tuple(row[column] for column in self.columns))

    def drain(self) -> list[ValidationFailure]:
        drained = list(self.records)
        self.records.clear()
        return drained
