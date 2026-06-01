from __future__ import annotations

from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class DefiLlamaStablecoinClient(BaseIngestionClient):
    source_name = "defillama_stablecoin"
    target_table = "stablecoin_liquidity_growth"
    endpoint_url = "https://stablecoins.llama.fi/stablecoincharts/all"
    schema = (
        timestamp_field(),
        SchemaField("token_symbol", FieldType.STRING),
        SchemaField("circulating_supply", FieldType.FLOAT, min_value=0.00000001),
        SchemaField("daily_growth_pct", FieldType.FLOAT),
        SchemaField("weekly_growth_pct", FieldType.FLOAT),
        SchemaField("monthly_growth_pct", FieldType.FLOAT),
    )
    duplicate_keys = ("timestamp", "token_symbol")

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        rows = payload if isinstance(payload, list) else payload.get("peggedAssets", [])
        if not isinstance(rows, list):
            raise ValueError("Unexpected DefiLlama stablecoin payload.")

        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol") or row.get("name") or "ALL"
            circulating = row.get("circulating")
            supply = row.get("circulating_supply")
            if supply is None and isinstance(circulating, dict):
                supply = circulating.get("peggedUSD")
            if supply is None:
                supply = row.get("totalCirculatingUSD")
            records.append(
                {
                    "timestamp": row.get("date") or row.get("timestamp"),
                    "token_symbol": symbol,
                    "circulating_supply": supply,
                    "daily_growth_pct": row.get("daily_growth_pct") or row.get("change_1d") or 0.0,
                    "weekly_growth_pct": row.get("weekly_growth_pct") or row.get("change_7d") or 0.0,
                    "monthly_growth_pct": row.get("monthly_growth_pct") or row.get("change_30d") or 0.0,
                }
            )
        return records
