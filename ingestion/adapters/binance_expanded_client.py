from __future__ import annotations

from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class BinanceExpandedClient(BaseIngestionClient):
    source_name = "binance_expanded"
    target_table = "crypto_market_metrics_v2"
    schema = (
        timestamp_field(),
        SchemaField("ticker", FieldType.STRING),
        SchemaField("market_cap", FieldType.FLOAT, min_value=0.0),
        SchemaField("close_price", FieldType.FLOAT, min_value=0.00000001),
        SchemaField("volume_24h", FieldType.FLOAT, min_value=0.0),
    )
    duplicate_keys = ("timestamp", "ticker")

    def __init__(self, *, symbol: str = "BTCUSDT", interval: str = "1d", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.symbol = symbol
        self.interval = interval
        self.endpoint_url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={interval}&limit=100"
        )

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise ValueError("Unexpected Binance kline payload.")

        records: list[dict[str, Any]] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            records.append(
                {
                    "timestamp": row[0],
                    "ticker": self.symbol,
                    "market_cap": 0.0,
                    "close_price": row[4],
                    "volume_24h": row[5],
                }
            )
        return records
