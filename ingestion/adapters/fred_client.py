from __future__ import annotations

import os
from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class FREDClient(BaseIngestionClient):
    source_name = "fred"
    target_table = "macro_liquidity_indicators"
    schema = (
        timestamp_field(),
        SchemaField("indicator_code", FieldType.STRING),
        SchemaField("value", FieldType.FLOAT),
        SchemaField("revised", FieldType.INT, required=False, min_value=0.0, max_value=1.0),
        SchemaField("release_date", FieldType.TIMESTAMP),
    )
    duplicate_keys = ("timestamp", "indicator_code")

    def __init__(self, *, series_id: str = "WALCL", api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.series_id = series_id
        self.api_key = api_key or os.getenv("FRED_API_KEY", "")
        self.endpoint_url = (
            "https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={self.api_key}&file_type=json"
        )

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("observations") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Unexpected FRED observations payload.")
        records: list[dict[str, Any]] = []
        for row in rows:
            value = row.get("value")
            if value == ".":
                value = None
            records.append(
                {
                    "timestamp": row.get("date"),
                    "indicator_code": f"FRED_{self.series_id}",
                    "value": value,
                    "revised": 0,
                    "release_date": row.get("realtime_start") or row.get("date"),
                }
            )
        return records
