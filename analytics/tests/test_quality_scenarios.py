from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from ingestion.adapters.base_client import BaseIngestionClient, timestamp_field
from ingestion.adapters.alternative_me_client import AlternativeMeFearGreedClient
from ingestion.adapters.amfi_client import AMFIClient
from ingestion.adapters.binance_expanded_client import BinanceExpandedClient
from ingestion.adapters.bis_client import BISClient
from ingestion.adapters.coinbase_client import CoinbaseClient
from ingestion.adapters.coingecko_expanded_client import CoinGeckoExpandedClient
from ingestion.adapters.defillama_stablecoin_client import DefiLlamaStablecoinClient
from ingestion.adapters.exchange_flow_client import ExchangeFlowClient
from ingestion.adapters.fred_client import FREDClient
from ingestion.adapters.government_capex_client import GovernmentCapexClient
from ingestion.adapters.gst_collections_client import GSTCollectionsClient
from ingestion.adapters.nse_client import NSEClient
from ingestion.adapters.oecd_client import OECDClient
from ingestion.adapters.pmi_client import PMIClient
from ingestion.adapters.rbi_liquidity_client import RBILiquidityClient
from ingestion.adapters.us_treasury_client import USTreasuryClient
from ingestion.adapters.world_bank_client import WorldBankClient
from ingestion.adapters.yfinance_client import YFinanceClient
from ingestion.persistence import PHASE1_TABLE_COLUMNS, Phase1Persistence
from ingestion.data_quality.exception_logger import StructuredExceptionLogger
from ingestion.data_quality.quality_inspector import FieldType, QualityInspector, SchemaField


MARKET_SCHEMA = (
    timestamp_field(),
    SchemaField("asset_id", FieldType.STRING),
    SchemaField("open_price", FieldType.FLOAT, min_value=0.00000001),
    SchemaField("high_price", FieldType.FLOAT, min_value=0.00000001),
    SchemaField("low_price", FieldType.FLOAT, min_value=0.00000001),
    SchemaField("close_price", FieldType.FLOAT, min_value=0.00000001),
    SchemaField("volume", FieldType.FLOAT, min_value=0.0),
)


class StaticMarketClient(BaseIngestionClient):
    source_name = "static_market"
    schema = MARKET_SCHEMA
    duplicate_keys = ("timestamp", "asset_id")

    def __init__(self, payload: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.payload = payload

    def fetch_raw(self) -> Any:
        return self.payload

    def parse_records(self, payload: Any) -> list[dict[str, Any]]:
        return list(payload)


class FlakyMarketClient(StaticMarketClient):
    def __init__(self, payload: list[dict[str, Any]], failures: int, **kwargs: Any) -> None:
        super().__init__(payload, **kwargs)
        self.failures = failures
        self.calls = 0

    def fetch_raw(self) -> Any:
        self.calls += 1
        if self.calls <= self.failures:
            raise OSError("temporary network dropout")
        return self.payload


class TimeoutMarketClient(StaticMarketClient):
    def fetch_raw(self) -> Any:
        raise TimeoutError("request timed out")


class Phase3QualityScenarioTest(unittest.TestCase):
    def test_quality_inspector_handles_null_duplicates_utc_and_outliers(self) -> None:
        logger = StructuredExceptionLogger()
        inspector = QualityInspector(logger=logger)
        records = [
            {
                "timestamp": f"2026-05-{index + 1:02d}T09:15:00+05:30",
                "asset_id": "NIFTY_50",
                "open_price": 100 + index,
                "high_price": 101 + index,
                "low_price": 99 + index,
                "close_price": 100 + index,
                "volume": 1000 + index,
            }
            for index in range(20)
        ]
        records.append(dict(records[0]))
        records.append(
            {
                "timestamp": "2026-05-22T09:15:00+05:30",
                "asset_id": "NIFTY_50",
                "open_price": 10000.0,
                "high_price": 10001.0,
                "low_price": 9999.0,
                "close_price": 10000.0,
                "volume": 1000.0,
            }
        )
        records.append(
            {
                "timestamp": "2026-05-23T09:15:00+05:30",
                "asset_id": "NIFTY_50",
                "open_price": None,
                "high_price": 101.0,
                "low_price": 99.0,
                "close_price": 100.0,
                "volume": 1000.0,
            }
        )

        result = inspector.inspect(
            source_name="unit_source",
            records=records,
            schema=MARKET_SCHEMA,
            timestamp_field="timestamp",
            duplicate_keys=("timestamp", "asset_id"),
        )

        self.assertEqual(result.duplicate_records, 1)
        self.assertEqual(len(result.accepted_records), 20)
        self.assertTrue(all(row["timestamp"].tzinfo == timezone.utc for row in result.accepted_records))
        exception_types = {exception.exception_type for exception in result.exceptions}
        self.assertIn("NULL_REQUIRED_FIELD", exception_types)
        self.assertIn("DUPLICATE_RECORD", exception_types)
        self.assertIn("OUTLIER_ZSCORE", exception_types)
        self.assertLess(result.quality_score, 100.0)
        self.assertEqual(len(logger.records), len(result.exceptions))

    def test_retry_logic_recovers_from_api_dropout(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        client = FlakyMarketClient(
            payload=[
                {
                    "timestamp": now,
                    "asset_id": "NIFTY_50",
                    "open_price": 100.0,
                    "high_price": 101.0,
                    "low_price": 99.0,
                    "close_price": 100.5,
                    "volume": 1000.0,
                }
            ],
            failures=1,
            max_retries=2,
        )

        result = client.run()

        self.assertTrue(result.success)
        self.assertEqual(client.calls, 2)
        self.assertGreater(result.health.source_health_score, 90.0)
        self.assertEqual(result.exceptions[0].exception_type, "FETCH_ERROR")

    def test_timeout_handling_returns_structured_failure(self) -> None:
        client = TimeoutMarketClient(payload=[], max_retries=1)

        result = client.run()

        self.assertFalse(result.success)
        self.assertEqual(result.records, [])
        self.assertEqual([exception.exception_type for exception in result.exceptions], ["TIMEOUT", "TIMEOUT"])
        self.assertEqual(result.health.availability_rate, 0.0)
        self.assertLess(result.health.source_health_score, 70.0)

    def test_nse_fallback_triggers_on_primary_connection_error(self) -> None:
        fallback = StaticMarketClient(
            source_name_payload(),
            max_retries=0,
        )

        class FailingNSEClient(NSEClient):
            def fetch_raw(self) -> Any:
                raise OSError("nse unavailable")

        client = FailingNSEClient(fallback_client=fallback, max_retries=0)
        result = client.run()

        self.assertTrue(result.success)
        self.assertTrue(result.metadata["fallback_triggered"])
        self.assertEqual(result.metadata["fallback_source"], "static_market")
        self.assertEqual(result.source_name, "nse")

    def test_every_adapter_declares_required_quality_controls(self) -> None:
        adapters = [
            AMFIClient(max_retries=0),
            NSEClient(max_retries=0),
            YFinanceClient(max_retries=0),
            RBILiquidityClient(max_retries=0),
            ExchangeFlowClient(max_retries=0),
            GSTCollectionsClient(max_retries=0),
            PMIClient(max_retries=0),
            GovernmentCapexClient(max_retries=0),
            FREDClient(api_key="test", max_retries=0),
            USTreasuryClient(max_retries=0),
            BISClient(max_retries=0),
            OECDClient(max_retries=0),
            WorldBankClient(max_retries=0),
            BinanceExpandedClient(max_retries=0),
            CoinbaseClient(max_retries=0),
            CoinGeckoExpandedClient(max_retries=0),
            DefiLlamaStablecoinClient(max_retries=0),
            AlternativeMeFearGreedClient(max_retries=0),
        ]

        for adapter in adapters:
            with self.subTest(adapter=adapter.source_name):
                self.assertTrue(all(adapter.quality_controls.values()))
                self.assertTrue(adapter.schema)
                self.assertTrue(adapter.duplicate_keys)
                self.assertGreater(adapter.timeout_seconds, 0.0)
                self.assertIn(adapter.target_table, PHASE1_TABLE_COLUMNS)

    def test_adapter_payload_parsers_produce_valid_records_under_mock_payloads(self) -> None:
        now = datetime.now(timezone.utc)
        cases: list[tuple[BaseIngestionClient, Any]] = [
            (
                YFinanceClient(max_retries=0),
                {
                    "chart": {
                        "result": [
                            {
                                "timestamp": [int(now.timestamp())],
                                "indicators": {
                                    "quote": [
                                        {
                                            "open": [100.0],
                                            "high": [101.0],
                                            "low": [99.0],
                                            "close": [100.5],
                                            "volume": [1000.0],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                },
            ),
            (
                BinanceExpandedClient(max_retries=0),
                [[int(now.timestamp() * 1000), "100", "101", "99", "100.5", "1234"]],
            ),
            (
                CoinbaseClient(max_retries=0),
                [[int(now.timestamp()), 99.0, 101.0, 100.0, 100.5, 1234.0]],
            ),
            (
                CoinGeckoExpandedClient(max_retries=0),
                {
                    "data": {
                        "market_cap_percentage": {"btc": 50.0},
                        "total_market_cap": {"usd": 2_000_000.0},
                        "total_volume": {"usd": 100_000.0},
                    }
                },
            ),
            (
                DefiLlamaStablecoinClient(max_retries=0),
                [
                    {
                        "date": int(now.timestamp()),
                        "symbol": "USDT",
                        "circulating_supply": 1000000.0,
                    }
                ],
            ),
            (
                RBILiquidityClient(max_retries=0),
                {
                    "records": [
                        {
                            "date": now.isoformat(),
                            "total_assets": 1.0,
                            "net_laf": 0.0,
                            "msf": 0.0,
                            "sdf": 0.0,
                            "credit_growth_yoy": 0.1,
                            "deposit_growth_yoy": 0.1,
                        }
                    ]
                },
            ),
            (
                ExchangeFlowClient(max_retries=0),
                {"records": [{"date": now.isoformat(), "fii": 1.0, "dii": 1.0}]},
            ),
            (
                AMFIClient(max_retries=0),
                {"data": [{"date": now.strftime("%d-%m-%Y"), "nav": "10.50"}]},
            ),
            (
                GSTCollectionsClient(max_retries=0),
                {"records": [{"date": now.isoformat(), "gross_gst_revenue": 100.0}]},
            ),
            (
                PMIClient(max_retries=0),
                {"records": [{"date": now.isoformat(), "pmi": 52.1}]},
            ),
            (
                GovernmentCapexClient(max_retries=0),
                {"records": [{"date": now.isoformat(), "capital_expenditure": 1000.0}]},
            ),
            (
                FREDClient(api_key="test", max_retries=0),
                {"observations": [{"date": now.date().isoformat(), "value": "1.5", "realtime_start": now.date().isoformat()}]},
            ),
            (
                USTreasuryClient(max_retries=0),
                {"data": [{"record_date": now.date().isoformat(), "avg_interest_rate_amt": "4.5"}]},
            ),
            (
                BISClient(max_retries=0),
                {"data": [{"date": now.date().isoformat(), "series": "BIS_TEST", "value": 1.0}]},
            ),
            (
                OECDClient(max_retries=0),
                {"data": [{"date": now.date().isoformat(), "series": "OECD_TEST", "value": 1.0}]},
            ),
            (
                WorldBankClient(max_retries=0),
                [{}, [{"date": str(now.year), "value": 100.0}]],
            ),
            (
                AlternativeMeFearGreedClient(max_retries=0),
                {"data": [{"timestamp": int(now.timestamp()), "value": "50"}]},
            ),
        ]

        for client, payload in cases:
            with self.subTest(client=client.source_name):
                client.fetch_raw = lambda payload=payload: payload  # type: ignore[method-assign]
                result = client.run()
                self.assertTrue(result.success)
                self.assertTrue(result.records)
                self.assertGreater(result.health.source_health_score, 90.0)

    def test_phase1_persistence_paths_are_whitelisted(self) -> None:
        persistence = Phase1Persistence()
        connection = FakeConnection()
        client = StaticMarketClient(source_name_payload(), max_retries=0)
        result = client.run()

        persistence.persist_fetch_result(connection, result, "daily_market_metrics")

        written_tables = [sql.split(" ")[2] for sql, _values in connection.statements]
        self.assertIn("daily_market_metrics", written_tables)
        self.assertIn("ingestion_source_health", written_tables)

        with self.assertRaises(ValueError):
            persistence.insert_rows(connection, "phase4_future_table", [{"timestamp": datetime.now(timezone.utc)}])


def source_name_payload() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "timestamp": now,
            "asset_id": "NIFTY_50",
            "open_price": 100.0,
            "high_price": 101.0,
            "low_price": 99.0,
            "close_price": 100.5,
            "volume": 1000.0,
        }
    ]


class FakeCursor:
    def __init__(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        self.statements = statements

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, sql: str, values: tuple[Any, ...]) -> None:
        self.statements.append((sql, values))


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.statements)


if __name__ == "__main__":
    unittest.main()
