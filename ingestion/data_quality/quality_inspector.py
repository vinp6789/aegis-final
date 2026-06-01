from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from statistics import mean, pstdev
from typing import Any, Iterable, Mapping, Sequence

from ingestion.data_quality.exception_logger import (
    ExceptionSeverity,
    QualityException,
    StructuredExceptionLogger,
)


class FieldType(str, Enum):
    STRING = "string"
    FLOAT = "float"
    INT = "int"
    TIMESTAMP = "timestamp"


@dataclass(frozen=True)
class SchemaField:
    name: str
    field_type: FieldType
    required: bool = True
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class QualityCheckResult:
    source_name: str
    accepted_records: list[dict[str, Any]]
    rejected_records: int
    duplicate_records: int
    exceptions: list[QualityException]
    quality_score: float
    missing_value_ratio: float
    validation_success_rate: float


@dataclass
class QualityInspector:
    logger: StructuredExceptionLogger = field(default_factory=StructuredExceptionLogger)
    outlier_z_threshold: float = 3.5

    def inspect(
        self,
        *,
        source_name: str,
        records: Iterable[Mapping[str, Any]],
        schema: Sequence[SchemaField],
        timestamp_field: str,
        duplicate_keys: Sequence[str],
    ) -> QualityCheckResult:
        source_records = list(records)
        exceptions: list[QualityException] = []
        normalized: list[dict[str, Any]] = []
        rejected_records = 0
        missing_values = 0
        inspected_values = 0

        for row_index, record in enumerate(source_records):
            normalized_record: dict[str, Any] = {}
            row_rejected = False
            for field_spec in schema:
                inspected_values += 1
                raw_value = record.get(field_spec.name)
                if raw_value is None or raw_value == "":
                    missing_values += 1
                    if field_spec.required:
                        exceptions.append(
                            self._exception(
                                source_name=source_name,
                                field_name=field_spec.name,
                                exception_type="NULL_REQUIRED_FIELD",
                                bad_value_raw=raw_value,
                                severity=ExceptionSeverity.HIGH,
                                message=f"Required field is null at row {row_index}.",
                            )
                        )
                        row_rejected = True
                    continue

                try:
                    normalized_value = self._coerce_value(raw_value, field_spec.field_type)
                    self._validate_bounds(source_name, field_spec, normalized_value, exceptions)
                except ValueError as exc:
                    exceptions.append(
                        self._exception(
                            source_name=source_name,
                            field_name=field_spec.name,
                            exception_type="SCHEMA_VALIDATION_ERROR",
                            bad_value_raw=raw_value,
                            severity=ExceptionSeverity.HIGH,
                            message=str(exc),
                        )
                    )
                    row_rejected = True
                    continue

                normalized_record[field_spec.name] = normalized_value

            if row_rejected:
                rejected_records += 1
            else:
                if timestamp_field in normalized_record:
                    normalized_record[timestamp_field] = self.normalize_timestamp(
                        normalized_record[timestamp_field]
                    )
                normalized.append(normalized_record)

        deduped, duplicate_records, duplicate_exceptions = self._dedupe_records(
            source_name=source_name,
            records=normalized,
            duplicate_keys=duplicate_keys,
        )
        exceptions.extend(duplicate_exceptions)

        accepted_records, outlier_exceptions = self._remove_outliers(
            source_name=source_name,
            records=deduped,
            schema=schema,
        )
        exceptions.extend(outlier_exceptions)
        rejected_records += len(deduped) - len(accepted_records)

        self.logger.log_many(exceptions)

        total_records = len(source_records)
        missing_value_ratio = missing_values / inspected_values if inspected_values else 0.0
        validation_success_rate = (
            len(accepted_records) / total_records if total_records else 0.0
        )
        quality_score = self._score(
            total_records=total_records,
            accepted_records=len(accepted_records),
            missing_value_ratio=missing_value_ratio,
            duplicate_records=duplicate_records,
            exception_count=len(exceptions),
        )

        return QualityCheckResult(
            source_name=source_name,
            accepted_records=accepted_records,
            rejected_records=rejected_records,
            duplicate_records=duplicate_records,
            exceptions=exceptions,
            quality_score=quality_score,
            missing_value_ratio=missing_value_ratio,
            validation_success_rate=validation_success_rate,
        )

    @staticmethod
    def normalize_timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            raw = float(value)
            parsed = datetime.fromtimestamp(raw / 1000 if raw > 10_000_000_000 else raw, timezone.utc)
        elif isinstance(value, str):
            cleaned = value.strip()
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(cleaned)
            except ValueError as exc:
                for date_format in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y"):
                    try:
                        parsed = datetime.strptime(cleaned, date_format)
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(f"Invalid timestamp: {value}") from exc
        else:
            raise ValueError(f"Invalid timestamp type: {type(value).__name__}")

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _exception(
        self,
        *,
        source_name: str,
        field_name: str,
        exception_type: str,
        bad_value_raw: Any,
        severity: ExceptionSeverity,
        message: str,
    ) -> QualityException:
        return QualityException(
            timestamp=datetime.now(timezone.utc),
            source_name=source_name,
            field_name=field_name,
            exception_type=exception_type,
            bad_value_raw=None if bad_value_raw is None else str(bad_value_raw),
            severity=severity,
            message=message,
        )

    def _coerce_value(self, value: Any, field_type: FieldType) -> Any:
        if field_type is FieldType.TIMESTAMP:
            return self.normalize_timestamp(value)
        if field_type is FieldType.STRING:
            return str(value)
        if field_type is FieldType.FLOAT:
            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                raise ValueError("Float value must be finite.")
            return numeric_value
        if field_type is FieldType.INT:
            numeric_value = int(value)
            return numeric_value
        raise ValueError(f"Unsupported field type: {field_type}")

    def _validate_bounds(
        self,
        source_name: str,
        field_spec: SchemaField,
        value: Any,
        exceptions: list[QualityException],
    ) -> None:
        if field_spec.field_type not in {FieldType.FLOAT, FieldType.INT}:
            return
        numeric_value = float(value)
        if field_spec.min_value is not None and numeric_value < field_spec.min_value:
            exceptions.append(
                self._exception(
                    source_name=source_name,
                    field_name=field_spec.name,
                    exception_type="MIN_VALUE_VIOLATION",
                    bad_value_raw=value,
                    severity=ExceptionSeverity.HIGH,
                    message=f"{field_spec.name} is below minimum {field_spec.min_value}.",
                )
            )
            raise ValueError(f"{field_spec.name} is below minimum {field_spec.min_value}.")
        if field_spec.max_value is not None and numeric_value > field_spec.max_value:
            exceptions.append(
                self._exception(
                    source_name=source_name,
                    field_name=field_spec.name,
                    exception_type="MAX_VALUE_VIOLATION",
                    bad_value_raw=value,
                    severity=ExceptionSeverity.HIGH,
                    message=f"{field_spec.name} is above maximum {field_spec.max_value}.",
                )
            )
            raise ValueError(f"{field_spec.name} is above maximum {field_spec.max_value}.")

    def _dedupe_records(
        self,
        *,
        source_name: str,
        records: Sequence[dict[str, Any]],
        duplicate_keys: Sequence[str],
    ) -> tuple[list[dict[str, Any]], int, list[QualityException]]:
        seen: set[tuple[Any, ...]] = set()
        deduped: list[dict[str, Any]] = []
        exceptions: list[QualityException] = []
        duplicate_count = 0
        for record in records:
            key = tuple(record.get(key_part) for key_part in duplicate_keys)
            if key in seen:
                duplicate_count += 1
                exceptions.append(
                    self._exception(
                        source_name=source_name,
                        field_name=",".join(duplicate_keys),
                        exception_type="DUPLICATE_RECORD",
                        bad_value_raw=key,
                        severity=ExceptionSeverity.MEDIUM,
                        message="Duplicate record removed before persistence.",
                    )
                )
                continue
            seen.add(key)
            deduped.append(record)
        return deduped, duplicate_count, exceptions

    def _remove_outliers(
        self,
        *,
        source_name: str,
        records: Sequence[dict[str, Any]],
        schema: Sequence[SchemaField],
    ) -> tuple[list[dict[str, Any]], list[QualityException]]:
        numeric_fields = [
            field_spec.name
            for field_spec in schema
            if field_spec.field_type in {FieldType.FLOAT, FieldType.INT}
        ]
        outlier_indexes: set[int] = set()
        exceptions: list[QualityException] = []

        for field_name in numeric_fields:
            values = [
                float(record[field_name])
                for record in records
                if field_name in record and record[field_name] is not None
            ]
            if len(values) < 3:
                continue
            avg = mean(values)
            deviation = pstdev(values)
            if deviation == 0.0:
                continue
            for index, record in enumerate(records):
                if field_name not in record:
                    continue
                z_score = abs((float(record[field_name]) - avg) / deviation)
                if z_score > self.outlier_z_threshold:
                    outlier_indexes.add(index)
                    exceptions.append(
                        self._exception(
                            source_name=source_name,
                            field_name=field_name,
                            exception_type="OUTLIER_ZSCORE",
                            bad_value_raw=record[field_name],
                            severity=ExceptionSeverity.HIGH,
                            message=f"Z-score {z_score:.4f} exceeds {self.outlier_z_threshold}.",
                        )
                    )

        return [
            record for index, record in enumerate(records) if index not in outlier_indexes
        ], exceptions

    @staticmethod
    def _score(
        *,
        total_records: int,
        accepted_records: int,
        missing_value_ratio: float,
        duplicate_records: int,
        exception_count: int,
    ) -> float:
        if total_records == 0:
            return 0.0
        rejection_penalty = (total_records - accepted_records) / total_records * 45.0
        null_penalty = missing_value_ratio * 25.0
        duplicate_penalty = duplicate_records / total_records * 15.0
        exception_penalty = min(exception_count * 2.5, 25.0)
        return round(max(0.0, 100.0 - rejection_penalty - null_penalty - duplicate_penalty - exception_penalty), 2)
