from __future__ import annotations

from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class CoinbaseClient(BaseIngestionClient):
    source_name = "coinbase"
    target_table = "crypto_market_metrics_v2"
    schema = (
        timestamp_field(),
        SchemaField("ticker", FieldType.STRING),
        SchemaField("market_cap", FieldType.FLOAT, min_value=0.0),
        SchemaField("close_price", FieldType.FLOAT, min_value=0.00000001),
        SchemaField("volume_24h", FieldType.FLOAT, min_value=0.0),
    )
    duplicate_keys = ("timestamp", "ticker")

    def __init__(self, *, product_id: str = "BTC-USD", granularity: int = 86_400, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.product_id = product_id
        self.granularity = granularity
        self.endpoint_url = (
            f"https://api.exchange.coinbase.com/products/{product_id}/candles"
            f"?granularity={granularity}"
        )

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise ValueError("Unexpected Coinbase candles payload.")
        records: list[dict[str, Any]] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            records.append(
                {
                    "timestamp": row[0],
                    "ticker": self.product_id.replace("-", ""),
                    "market_cap": 0.0,
                    "close_price": row[4],
                    "volume_24h": row[5],
                }
            )
        return records
