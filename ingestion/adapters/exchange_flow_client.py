from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class ExchangeFlowClient(BaseIngestionClient):
    source_name = "exchange_flow"
    target_table = "india_liquidity_flows"
    endpoint_url = "https://www.fpi.nsdl.co.in/"
    schema = (
        timestamp_field(),
        SchemaField("fii_net_flow_usd", FieldType.FLOAT),
        SchemaField("dii_net_flow_inr", FieldType.FLOAT),
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
            raise ValueError("Unexpected exchange flow payload.")

        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            records.append(
                {
                    "timestamp": row.get("timestamp") or row.get("date") or datetime.now(timezone.utc),
                    "fii_net_flow_usd": row.get("fii_net_flow_usd") or row.get("fii"),
                    "dii_net_flow_inr": row.get("dii_net_flow_inr") or row.get("dii"),
                }
            )
        return records
