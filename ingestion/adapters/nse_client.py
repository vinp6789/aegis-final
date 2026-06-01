from __future__ import annotations

from dataclasses import replace
from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, FetchResult, timestamp_field
from ingestion.adapters.yfinance_client import YFinanceClient
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class NSEClient(BaseIngestionClient):
    source_name = "nse"
    target_table = "daily_market_metrics"
    endpoint_url = "https://www.nseindia.com/api/allIndices"
    schema = (
        timestamp_field(),
        SchemaField("asset_id", FieldType.STRING),
        SchemaField("open_price", FieldType.FLOAT, min_value=0.00000001),
        SchemaField("high_price", FieldType.FLOAT, min_value=0.00000001),
        SchemaField("low_price", FieldType.FLOAT, min_value=0.00000001),
        SchemaField("close_price", FieldType.FLOAT, min_value=0.00000001),
        SchemaField("volume", FieldType.FLOAT, min_value=0.0),
        SchemaField("market_cap", FieldType.FLOAT, required=False, min_value=0.0),
    )
    duplicate_keys = ("timestamp", "asset_id")

    def __init__(self, *, fallback_client: BaseIngestionClient | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.fallback_client = fallback_client or YFinanceClient(
            logger=self.logger,
            inspector=self.inspector,
            timeout_seconds=self.timeout_seconds,
            max_retries=0,
        )

    def run(self) -> FetchResult:
        primary_result = super().run()
        if primary_result.success:
            return primary_result
        fallback_result = self.fallback_client.run()
        return replace(
            fallback_result,
            source_name=self.source_name,
            exceptions=primary_result.exceptions + fallback_result.exceptions,
            metadata={
                **fallback_result.metadata,
                "fallback_triggered": True,
                "fallback_source": fallback_result.source_name,
            },
        )

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Unexpected NSE allIndices payload.")

        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset_id = row.get("indexSymbol") or row.get("index") or row.get("symbol")
            close_price = row.get("last") or row.get("lastPrice") or row.get("close")
            records.append(
                {
                    "timestamp": row.get("timestamp") or row.get("asOf") or row.get("date"),
                    "asset_id": asset_id,
                    "open_price": row.get("open") or close_price,
                    "high_price": row.get("high") or close_price,
                    "low_price": row.get("low") or close_price,
                    "close_price": close_price,
                    "volume": row.get("totalTradedVolume") or row.get("volume") or 0.0,
                    "market_cap": row.get("marketCap"),
                }
            )
        return records
