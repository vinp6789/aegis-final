from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from analytics.validation.exception_logger import (
    FailureAction,
    StructuredValidationExceptionLogger,
    ValidationFailure,
    ValidationRule,
    ValidationSeverity,
)


class FieldType(str, Enum):
    STRING = "string"
    FLOAT = "float"
    INT = "int"
    TIMESTAMP = "timestamp"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class SchemaField:
    name: str
    field_type: FieldType
    required: bool = True
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class SchemaValidationResult:
    records: list[dict[str, Any]]
    failures: list[ValidationFailure]
    valid_record_indexes: list[int]
    blocked_record_indexes: list[int]


REQUIRED_FIELD_RULE = ValidationRule(
    rule_name="SCHEMA_REQUIRED_FIELD",
    description="Required schema fields must be present and non-empty.",
    threshold="required=True",
    severity=ValidationSeverity.CRITICAL,
    failure_action=FailureAction.FLAG_RECORD,
)

FIELD_TYPE_RULE = ValidationRule(
    rule_name="SCHEMA_FIELD_TYPE",
    description="Values must be coercible to the declared schema field type.",
    threshold="declared FieldType",
    severity=ValidationSeverity.CRITICAL,
    failure_action=FailureAction.FLAG_RECORD,
)

NUMERIC_BOUNDS_RULE = ValidationRule(
    rule_name="SCHEMA_NUMERIC_BOUNDS",
    description="Numeric values must remain within declared minimum and maximum bounds.",
    threshold="SchemaField.min_value <= value <= SchemaField.max_value",
    severity=ValidationSeverity.CRITICAL,
    failure_action=FailureAction.FLAG_RECORD,
)

SCHEMA_VALIDATION_RULES = (
    REQUIRED_FIELD_RULE,
    FIELD_TYPE_RULE,
    NUMERIC_BOUNDS_RULE,
)


class SchemaValidator:
    rules = SCHEMA_VALIDATION_RULES

    def __init__(self, logger: StructuredValidationExceptionLogger | None = None) -> None:
        self.logger = logger or StructuredValidationExceptionLogger()

    def validate(
        self,
        *,
        source_name: str,
        records: Sequence[Mapping[str, Any]],
        schema: Sequence[SchemaField],
    ) -> SchemaValidationResult:
        materialized = [dict(record) for record in records]
        failures: list[ValidationFailure] = []
        blocked_indexes: set[int] = set()

        for index, record in enumerate(materialized):
            for field in schema:
                value = record.get(field.name)
                if value is None or value == "":
                    if field.required:
                        failures.append(
                            self.logger.build_failure(
                                source_name=source_name,
                                field_name=field.name,
                                rule=REQUIRED_FIELD_RULE,
                                bad_value_raw=value,
                                message=f"{field.name} is required.",
                                record_index=index,
                            )
                        )
                        blocked_indexes.add(index)
                    continue

                try:
                    coerced = self._coerce(value, field.field_type)
                except ValueError as exc:
                    failures.append(
                        self.logger.build_failure(
                            source_name=source_name,
                            field_name=field.name,
                            rule=FIELD_TYPE_RULE,
                            bad_value_raw=value,
                            message=str(exc),
                            record_index=index,
                        )
                    )
                    blocked_indexes.add(index)
                    continue

                try:
                    self._validate_bounds(field, coerced)
                except ValueError as exc:
                    failures.append(
                        self.logger.build_failure(
                            source_name=source_name,
                            field_name=field.name,
                            rule=NUMERIC_BOUNDS_RULE,
                            bad_value_raw=value,
                            message=str(exc),
                            record_index=index,
                        )
                    )
                    blocked_indexes.add(index)

        self.logger.log_many(failures)
        return SchemaValidationResult(
            records=materialized,
            failures=failures,
            valid_record_indexes=[
                index for index in range(len(materialized)) if index not in blocked_indexes
            ],
            blocked_record_indexes=sorted(blocked_indexes),
        )

    @staticmethod
    def _coerce(value: Any, field_type: FieldType) -> Any:
        if field_type is FieldType.STRING:
            return str(value)
        if field_type is FieldType.FLOAT:
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("Float value must be finite.")
            return numeric
        if field_type is FieldType.INT:
            if isinstance(value, bool):
                raise ValueError("Boolean is not a valid integer value.")
            return int(value)
        if field_type is FieldType.BOOLEAN:
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in {"true", "false"}:
                return value.lower() == "true"
            raise ValueError("Value must be boolean.")
        if field_type is FieldType.TIMESTAMP:
            return SchemaValidator._coerce_timestamp(value)
        raise ValueError(f"Unsupported field type: {field_type}")

    @staticmethod
    def _coerce_timestamp(value: Any) -> datetime:
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

    @staticmethod
    def _validate_bounds(field: SchemaField, value: Any) -> None:
        if field.field_type not in {FieldType.FLOAT, FieldType.INT}:
            return
        numeric = float(value)
        if field.min_value is not None and numeric < field.min_value:
            raise ValueError(f"{field.name} is below minimum {field.min_value}.")
        if field.max_value is not None and numeric > field.max_value:
            raise ValueError(f"{field.name} is above maximum {field.max_value}.")
