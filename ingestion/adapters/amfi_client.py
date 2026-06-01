from __future__ import annotations

from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class AMFIClient(BaseIngestionClient):
    source_name = "amfi"
    target_table = "macro_liquidity_indicators"
    schema = (
        timestamp_field(),
        SchemaField("indicator_code", FieldType.STRING),
        SchemaField("value", FieldType.FLOAT, min_value=0.0),
        SchemaField("revised", FieldType.INT, required=False, min_value=0.0, max_value=1.0),
        SchemaField("release_date", FieldType.TIMESTAMP),
    )
    duplicate_keys = ("timestamp", "indicator_code")

    def __init__(self, *, scheme_code: str = "120503", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.scheme_code = scheme_code
        self.endpoint_url = f"https://api.mfapi.in/mf/{scheme_code}"

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Unexpected AMFI/mfapi payload.")
        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            date_value = row.get("date") or row.get("timestamp")
            records.append(
                {
                    "timestamp": date_value,
                    "indicator_code": f"AMFI_NAV_{self.scheme_code}",
                    "value": row.get("nav"),
                    "revised": 0,
                    "release_date": date_value,
                }
            )
        return records
