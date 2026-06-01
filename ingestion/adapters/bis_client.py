from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class BISClient(BaseIngestionClient):
    source_name = "bis"
    target_table = "macro_liquidity_indicators"
    endpoint_url = "https://stats.bis.org/api/v1/data"
    schema = (
        timestamp_field(),
        SchemaField("indicator_code", FieldType.STRING),
        SchemaField("value", FieldType.FLOAT),
        SchemaField("revised", FieldType.INT, required=False, min_value=0.0, max_value=1.0),
        SchemaField("release_date", FieldType.TIMESTAMP),
    )
    duplicate_keys = ("timestamp", "indicator_code")

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("data") or payload.get("observations") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("Unexpected BIS SDMX payload.")
        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            timestamp = row.get("timestamp") or row.get("date") or row.get("period") or datetime.now(timezone.utc)
            records.append(
                {
                    "timestamp": timestamp,
                    "indicator_code": row.get("indicator_code") or row.get("series") or "BIS_INDICATOR",
                    "value": row.get("value"),
                    "revised": 0,
                    "release_date": row.get("release_date") or timestamp,
                }
            )
        return records
