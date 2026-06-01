from __future__ import annotations

from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class USTreasuryClient(BaseIngestionClient):
    source_name = "us_treasury"
    target_table = "macro_liquidity_indicators"
    endpoint_url = (
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
        "v2/accounting/od/avg_interest_rates?sort=-record_date&page[size]=100"
    )
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
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Unexpected US Treasury payload.")
        records: list[dict[str, Any]] = []
        for row in rows:
            records.append(
                {
                    "timestamp": row.get("record_date"),
                    "indicator_code": "US_TREASURY_AVG_INTEREST_RATE",
                    "value": row.get("avg_interest_rate_amt"),
                    "revised": 0,
                    "release_date": row.get("record_date"),
                }
            )
        return records
