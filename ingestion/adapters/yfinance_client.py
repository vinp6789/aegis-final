from __future__ import annotations

from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.data_quality.quality_inspector import FieldType, SchemaField


class YFinanceClient(BaseIngestionClient):
    source_name = "yfinance"
    target_table = "daily_market_metrics"
    endpoint_url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI"
        "?range=10d&interval=1d"
    )
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

    def __init__(self, *, symbol: str = "^NSEI", asset_id: str = "NIFTY_50", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.symbol = symbol
        self.asset_id = asset_id
        encoded_symbol = symbol.replace("^", "%5E")
        self.endpoint_url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
            "?range=10d&interval=1d"
        )

    def fetch_raw(self) -> Any:
        return self.fetch_json_url(self.endpoint_url)

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        try:
            result = payload["chart"]["result"][0]
            timestamps = result["timestamp"]
            quote = result["indicators"]["quote"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Unexpected Yahoo chart payload.") from exc

        records: list[dict[str, Any]] = []
        for index, timestamp in enumerate(timestamps):
            records.append(
                {
                    "timestamp": timestamp,
                    "asset_id": self.asset_id,
                    "open_price": quote["open"][index],
                    "high_price": quote["high"][index],
                    "low_price": quote["low"][index],
                    "close_price": quote["close"][index],
                    "volume": quote.get("volume", [0])[index] or 0.0,
                    "market_cap": None,
                }
            )
        return records
