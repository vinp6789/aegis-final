from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class RBILiquidityClient(BaseIngestionClient):
    source_name = "rbi_liquidity"
    target_table = "india_liquidity_flows"
    endpoint_url = "https://dbie.rbi.org.in/"
    schema = (
        timestamp_field(),
        SchemaField("rbi_total_assets", FieldType.FLOAT, required=False, min_value=0.0),
        SchemaField("net_laf_absorption", FieldType.FLOAT, required=False),
        SchemaField("marginal_standing_facility", FieldType.FLOAT, required=False, min_value=0.0),
        SchemaField("standing_deposit_facility", FieldType.FLOAT, required=False, min_value=0.0),
        SchemaField("bank_credit_growth_yoy", FieldType.FLOAT),
        SchemaField("bank_deposit_growth_yoy", FieldType.FLOAT),
    )
    duplicate_keys = ("timestamp",)

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            rows = payload["records"]
        elif isinstance(payload, list):
            rows = payload
        else:
            raise ValueError("Unexpected RBI liquidity payload.")

        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            records.append(
                {
                    "timestamp": row.get("timestamp") or row.get("date") or datetime.now(timezone.utc),
                    "rbi_total_assets": row.get("rbi_total_assets") or row.get("total_assets"),
                    "net_laf_absorption": row.get("net_laf_absorption") or row.get("net_laf"),
                    "marginal_standing_facility": row.get("marginal_standing_facility") or row.get("msf"),
                    "standing_deposit_facility": row.get("standing_deposit_facility") or row.get("sdf"),
                    "bank_credit_growth_yoy": row.get("bank_credit_growth_yoy") or row.get("credit_growth_yoy"),
                    "bank_deposit_growth_yoy": row.get("bank_deposit_growth_yoy") or row.get("deposit_growth_yoy"),
                }
            )
        return records
