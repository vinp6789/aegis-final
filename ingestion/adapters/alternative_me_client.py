from __future__ import annotations

from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class AlternativeMeFearGreedClient(BaseIngestionClient):
    source_name = "alternative_me_fear_greed"
    target_table = "macro_liquidity_indicators"
    endpoint_url = "https://api.alternative.me/fng/?limit=100&format=json"
    schema = (
        timestamp_field(),
        SchemaField("indicator_code", FieldType.STRING),
        SchemaField("value", FieldType.FLOAT, min_value=0.0, max_value=100.0),
        SchemaField("revised", FieldType.INT, required=False, min_value=0.0, max_value=1.0),
        SchemaField("release_date", FieldType.TIMESTAMP),
    )
    duplicate_keys = ("timestamp", "indicator_code")

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Unexpected Alternative.me fear and greed payload.")
        records: list[dict[str, Any]] = []
        for row in rows:
            records.append(
                {
                    "timestamp": row.get("timestamp"),
                    "indicator_code": "CRYPTO_FEAR_GREED",
                    "value": row.get("value"),
                    "revised": 0,
                    "release_date": row.get("timestamp"),
                }
            )
        return records
