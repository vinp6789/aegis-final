from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ingestion.data_quality.exception_logger import (
    ExceptionSeverity,
    QualityException,
    StructuredExceptionLogger,
)
from ingestion.data_quality.quality_inspector import (
    FieldType,
    QualityCheckResult,
    QualityInspector,
    SchemaField,
)


@dataclass(frozen=True)
class SourceHealthMetrics:
    source_name: str
    availability_rate: float
    freshness_seconds: int
    missing_value_ratio: float
    average_latency_ms: int
    validation_success_rate: float
    source_health_score: float


@dataclass(frozen=True)
class FetchResult:
    source_name: str
    success: bool
    records: list[dict[str, Any]]
    quality_result: QualityCheckResult | None
    health: SourceHealthMetrics
    exceptions: list[QualityException]
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseIngestionClient(ABC):
    """Base client enforcing Phase 3 quality controls for every source."""

    source_name: str = "base"
    endpoint_url: str = ""
    target_table: str = ""
    timestamp_field: str = "timestamp"
    schema: Sequence[SchemaField] = ()
    duplicate_keys: Sequence[str] = ("timestamp",)
    timeout_seconds: float = 10.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.1
    user_agent: str = "AegisPhase3Ingestion/1.0"

    def __init__(
        self,
        *,
        logger: StructuredExceptionLogger | None = None,
        inspector: QualityInspector | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.logger = logger or StructuredExceptionLogger()
        self.inspector = inspector or QualityInspector(logger=self.logger)
        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds
        if max_retries is not None:
            self.max_retries = max_retries

    @property
    def quality_controls(self) -> dict[str, bool]:
        return {
            "retry_logic": self.max_retries >= 0,
            "timeout_handling": self.timeout_seconds > 0.0,
            "schema_validation": bool(self.schema),
            "null_handling": True,
            "duplicate_handling": bool(self.duplicate_keys),
            "timestamp_normalization_utc": True,
            "data_quality_scoring": True,
            "structured_error_logging": True,
        }

    def run(self) -> FetchResult:
        started = time.perf_counter()
        exceptions: list[QualityException] = []
        raw_payload: Any = None
        request_succeeded = False

        for attempt in range(1, self.max_retries + 2):
            try:
                raw_payload = self.fetch_raw()
                request_succeeded = True
                break
            except TimeoutError as exc:
                exceptions.append(
                    self._log_runtime_error(
                        exception_type="TIMEOUT",
                        severity=ExceptionSeverity.HIGH,
                        attempt=attempt,
                        error=exc,
                    )
                )
            except (urllib.error.URLError, OSError, ValueError) as exc:
                exceptions.append(
                    self._log_runtime_error(
                        exception_type="FETCH_ERROR",
                        severity=ExceptionSeverity.HIGH,
                        attempt=attempt,
                        error=exc,
                    )
                )
            if attempt <= self.max_retries:
                time.sleep(self.retry_backoff_seconds)

        latency_ms = int((time.perf_counter() - started) * 1000)
        if not request_succeeded:
            health = self._health(
                availability_rate=0.0,
                freshness_seconds=0,
                missing_value_ratio=1.0,
                average_latency_ms=latency_ms,
                validation_success_rate=0.0,
                quality_score=0.0,
            )
            return FetchResult(
                source_name=self.source_name,
                success=False,
                records=[],
                quality_result=None,
                health=health,
                exceptions=exceptions,
                metadata={"attempts": self.max_retries + 1},
            )

        try:
            parsed_records = self.parse_records(raw_payload)
            quality_result = self.inspector.inspect(
                source_name=self.source_name,
                records=parsed_records,
                schema=self.schema,
                timestamp_field=self.timestamp_field,
                duplicate_keys=self.duplicate_keys,
            )
        except ValueError as exc:
            exceptions.append(
                self._log_runtime_error(
                    exception_type="PARSE_ERROR",
                    severity=ExceptionSeverity.HIGH,
                    attempt=1,
                    error=exc,
                )
            )
            health = self._health(
                availability_rate=1.0,
                freshness_seconds=0,
                missing_value_ratio=1.0,
                average_latency_ms=latency_ms,
                validation_success_rate=0.0,
                quality_score=0.0,
            )
            return FetchResult(
                source_name=self.source_name,
                success=False,
                records=[],
                quality_result=None,
                health=health,
                exceptions=exceptions,
                metadata={"attempts": self.max_retries + 1},
            )

        exceptions.extend(quality_result.exceptions)
        freshness_seconds = self._freshness_seconds(quality_result.accepted_records)
        health = self._health(
            availability_rate=1.0,
            freshness_seconds=freshness_seconds,
            missing_value_ratio=quality_result.missing_value_ratio,
            average_latency_ms=latency_ms,
            validation_success_rate=quality_result.validation_success_rate,
            quality_score=quality_result.quality_score,
        )
        return FetchResult(
            source_name=self.source_name,
            success=bool(quality_result.accepted_records),
            records=quality_result.accepted_records,
            quality_result=quality_result,
            health=health,
            exceptions=exceptions,
            metadata={"attempts": self.max_retries + 1},
        )

    def fetch_json_url(self, url: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except TimeoutError:
            raise
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError(str(exc)) from exc
            raise

    @abstractmethod
    def fetch_raw(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _log_runtime_error(
        self,
        *,
        exception_type: str,
        severity: ExceptionSeverity,
        attempt: int,
        error: BaseException,
    ) -> QualityException:
        return self.logger.log(
            source_name=self.source_name,
            field_name="__request__",
            exception_type=exception_type,
            bad_value_raw=repr(error),
            severity=severity,
            message=f"{self.source_name} attempt {attempt} failed: {error}",
        )

    def _health(
        self,
        *,
        availability_rate: float,
        freshness_seconds: int,
        missing_value_ratio: float,
        average_latency_ms: int,
        validation_success_rate: float,
        quality_score: float,
    ) -> SourceHealthMetrics:
        latency_penalty = min(average_latency_ms / 1000.0, 20.0)
        freshness_penalty = min(freshness_seconds / 86_400.0, 10.0)
        score = (
            availability_rate * 40.0
            + validation_success_rate * 25.0
            + quality_score * 0.35
            - missing_value_ratio * 10.0
            - latency_penalty
            - freshness_penalty
        )
        return SourceHealthMetrics(
            source_name=self.source_name,
            availability_rate=round(max(0.0, min(1.0, availability_rate)), 4),
            freshness_seconds=max(0, int(freshness_seconds)),
            missing_value_ratio=round(max(0.0, min(1.0, missing_value_ratio)), 4),
            average_latency_ms=max(0, int(average_latency_ms)),
            validation_success_rate=round(max(0.0, min(1.0, validation_success_rate)), 4),
            source_health_score=round(max(0.0, min(100.0, score)), 2),
        )

    def _freshness_seconds(self, records: Sequence[Mapping[str, Any]]) -> int:
        timestamps = [
            record[self.timestamp_field]
            for record in records
            if isinstance(record.get(self.timestamp_field), datetime)
        ]
        if not timestamps:
            return 0
        latest = max(timestamps)
        return max(0, int((datetime.now(timezone.utc) - latest).total_seconds()))


def timestamp_field() -> SchemaField:
    return SchemaField("timestamp", FieldType.TIMESTAMP)
