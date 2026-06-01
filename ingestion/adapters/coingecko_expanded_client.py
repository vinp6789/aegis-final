from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class CoinGeckoExpandedClient(BaseIngestionClient):
    source_name = "coingecko_expanded"
    target_table = "crypto_market_metrics_v2"
    endpoint_url = "https://api.coingecko.com/api/v3/global"
    schema = (
        timestamp_field(),
        SchemaField("ticker", FieldType.STRING),
        SchemaField("market_cap", FieldType.FLOAT, min_value=0.0),
        SchemaField("close_price", FieldType.FLOAT, min_value=0.00000001),
        SchemaField("volume_24h", FieldType.FLOAT, min_value=0.0),
    )
    duplicate_keys = ("timestamp", "ticker")

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        try:
            data = payload["data"]
            market_cap_percentage = data["market_cap_percentage"]
            total_market_cap_usd = float(data["total_market_cap"]["usd"])
            volume_usd = float(data["total_volume"]["usd"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Unexpected CoinGecko global payload.") from exc

        timestamp = datetime.now(timezone.utc)
        records: list[dict[str, Any]] = []
        for ticker, percentage in market_cap_percentage.items():
            share = float(percentage) / 100.0
            records.append(
                {
                    "timestamp": timestamp,
                    "ticker": str(ticker).upper(),
                    "market_cap": total_market_cap_usd * share,
                    "close_price": 1.0,
                    "volume_24h": volume_usd * share,
                }
            )
        return records
