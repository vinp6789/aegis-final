from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class ExceptionSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class QualityException:
    timestamp: datetime
    source_name: str
    field_name: str
    exception_type: str
    bad_value_raw: str | None
    severity: ExceptionSeverity
    message: str

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["timestamp"] = self.timestamp.astimezone(timezone.utc).isoformat()
        record["severity"] = self.severity.value
        return record


class StructuredExceptionLogger:
    """Structured in-memory logger with optional JSONL persistence."""

    def __init__(self, sink_path: Path | None = None) -> None:
        self.sink_path = sink_path
        self.records: list[QualityException] = []

    def log(
        self,
        *,
        source_name: str,
        field_name: str,
        exception_type: str,
        bad_value_raw: Any,
        severity: ExceptionSeverity,
        message: str,
    ) -> QualityException:
        exception = QualityException(
            timestamp=datetime.now(timezone.utc),
            source_name=source_name,
            field_name=field_name,
            exception_type=exception_type,
            bad_value_raw=None if bad_value_raw is None else str(bad_value_raw),
            severity=severity,
            message=message,
        )
        self.records.append(exception)
        if self.sink_path is not None:
            self.sink_path.parent.mkdir(parents=True, exist_ok=True)
            with self.sink_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(exception.to_record(), sort_keys=True) + "\n")
        return exception

    def log_many(self, exceptions: Iterable[QualityException]) -> None:
        for exception in exceptions:
            self.records.append(exception)
            if self.sink_path is not None:
                self.sink_path.parent.mkdir(parents=True, exist_ok=True)
                with self.sink_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(exception.to_record(), sort_keys=True) + "\n")

    def drain(self) -> list[QualityException]:
        drained = list(self.records)
        self.records.clear()
        return drained
