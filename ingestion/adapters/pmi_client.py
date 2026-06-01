from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class PMIClient(BaseIngestionClient):
    source_name = "pmi"
    target_table = "macro_liquidity_indicators"
    schema = (
        timestamp_field(),
        SchemaField("indicator_code", FieldType.STRING),
        SchemaField("value", FieldType.FLOAT, min_value=0.0, max_value=100.0),
        SchemaField("revised", FieldType.INT, required=False, min_value=0.0, max_value=1.0),
        SchemaField("release_date", FieldType.TIMESTAMP),
    )
    duplicate_keys = ("timestamp", "indicator_code")

    def __init__(
        self,
        *,
        resource_id: str = "india-pmi",
        api_key: str = "579b464db66ec23bdd000001",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.resource_id = resource_id
        self.endpoint_url = (
            f"https://api.data.gov.in/resource/{resource_id}"
            f"?api-key={api_key}&format=json&limit=1000"
        )

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("Unexpected PMI payload.")
        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            timestamp = row.get("timestamp") or row.get("date") or row.get("month") or datetime.now(timezone.utc)
            records.append(
                {
                    "timestamp": timestamp,
                    "indicator_code": row.get("indicator_code") or "INDIA_PMI",
                    "value": row.get("value") or row.get("pmi"),
                    "revised": 0,
                    "release_date": row.get("release_date") or timestamp,
                }
            )
        return records
