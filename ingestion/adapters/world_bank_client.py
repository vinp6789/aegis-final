from __future__ import annotations

from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class WorldBankClient(BaseIngestionClient):
    source_name = "world_bank"
    target_table = "macro_liquidity_indicators"
    schema = (
        timestamp_field(),
        SchemaField("indicator_code", FieldType.STRING),
        SchemaField("value", FieldType.FLOAT),
        SchemaField("revised", FieldType.INT, required=False, min_value=0.0, max_value=1.0),
        SchemaField("release_date", FieldType.TIMESTAMP),
    )
    duplicate_keys = ("timestamp", "indicator_code")

    def __init__(
        self,
        *,
        country: str = "WLD",
        indicator: str = "NY.GDP.MKTP.CD",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.country = country
        self.indicator = indicator
        self.endpoint_url = (
            f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
            "?format=json&per_page=100"
        )

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else None
        if not isinstance(rows, list):
            raise ValueError("Unexpected World Bank indicator payload.")
        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or row.get("value") is None:
                continue
            records.append(
                {
                    "timestamp": f"{row.get('date')}-12-31",
                    "indicator_code": f"WORLD_BANK_{self.indicator}",
                    "value": row.get("value"),
                    "revised": 0,
                    "release_date": f"{row.get('date')}-12-31",
                }
            )
        return records
