from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from analytics.diagnostics.liquidity_engine import LiquiditySnapshot


class WorkerAggregatorInputTest(unittest.TestCase):
    def test_build_aggregator_input_uses_live_signal_helpers(self) -> None:
        worker_api = load_worker_api()
        liquidity = LiquiditySnapshot(
            timestamp=datetime(2026, 7, 12, tzinfo=timezone.utc),
            us_liquidity_index=55.0,
            india_liquidity_index=60.0,
            crypto_liquidity_index=65.0,
            global_liquidity_index=70.0,
            liquidity_transmission_score=75.0,
        )
        with (
            patch.object(worker_api, "latest_breadth_row", return_value={"leading_diffusion_index": -0.2, "hhi_concentration_score": 0.4, "regime_probability": 0.7}),
            patch.object(worker_api, "latest_systemic_stress", return_value=0.3),
            patch.object(worker_api, "latest_liquidity_snapshot", return_value=liquidity),
            patch.object(worker_api, "latest_discovery_score", return_value=82.0),
            patch.object(worker_api, "latest_market_volatility_index", return_value=24.0),
            patch.object(worker_api, "calculate_walk_forward_metrics", return_value={"forecast_accuracy_3m": 60.0, "forecast_accuracy_6m": 70.0, "forecast_accuracy_12m": 80.0, "panic_prediction_hit_rate": 90.0, "recovery_prediction_hit_rate": 50.0, "buy_signal_success_rate": 40.0, "sell_signal_success_rate": 30.0}),
        ):
            result = worker_api.build_aggregator_input()

        self.assertEqual(result.liquidity_index, 70.0)
        self.assertEqual(result.liquidity_transmission_score, 75.0)
        self.assertEqual(result.crypto_liquidity_index, 65.0)
        self.assertEqual(result.discovery_score, 82.0)
        self.assertEqual(result.volatility_index, 24.0)
        self.assertEqual(result.backtest_win_rate, 0.6)
        self.assertIsNone(result.backtest_sharpe)


def load_worker_api() -> types.ModuleType:
    sys.modules.pop("worker_api", None)
    fastapi = types.ModuleType("fastapi")
    fastapi.FastAPI = FakeFastAPI
    fastapi.HTTPException = FakeHTTPException
    psycopg2 = types.ModuleType("psycopg2")
    psycopg2.connect = lambda _url: None
    with patch.dict(sys.modules, {"fastapi": fastapi, "psycopg2": psycopg2}):
        return importlib.import_module("worker_api")


class FakeFastAPI:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def get(self, _path: str):
        return lambda function: function

    def post(self, _path: str):
        return lambda function: function


class FakeHTTPException(Exception):
    def __init__(self, **_kwargs: object) -> None:
        super().__init__()


if __name__ == "__main__":
    unittest.main()
