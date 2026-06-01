from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from analytics.validation.backtest_engine import (
    BacktestEngine,
    FeeRule,
    TradeSignal,
    load_fee_rules,
)


class Phase5BacktestEngineTest(unittest.TestCase):
    def test_static_returns_performance_statistics(self) -> None:
        engine = BacktestEngine(
            fee_rules={"test": FeeRule("test", fee_rate=0.0, slippage_rate=0.0)},
            trading_periods_per_year=4,
        )

        stats = engine.calculate_stats([0.10, -0.05, 0.02, 0.03])

        self.assertEqual(stats.observations, 4)
        self.assertAlmostEqual(stats.total_return, 0.097877)
        self.assertGreater(stats.cagr, 0.09)
        self.assertGreater(stats.sharpe, 0.0)
        self.assertGreater(stats.sortino, 0.0)
        self.assertLess(stats.max_drawdown, 0.0)
        self.assertEqual(stats.win_rate, 0.75)
        self.assertGreater(stats.volatility, 0.0)

    def test_fee_and_slippage_deduction_are_asset_class_specific(self) -> None:
        engine = BacktestEngine()
        signals = [
            signal(0, asset_class="india_equity", gross_return=0.01),
            signal(1, asset_class="crypto", gross_return=0.01),
        ]

        result = engine.run(signals)

        india = result.observations[0]
        crypto = result.observations[1]
        self.assertAlmostEqual(india.fee_cost, 0.0024)
        self.assertAlmostEqual(india.slippage_cost, 0.0010)
        self.assertAlmostEqual(india.net_return, 0.0066)
        self.assertAlmostEqual(crypto.fee_cost, 0.0020)
        self.assertAlmostEqual(crypto.slippage_cost, 0.0030)
        self.assertAlmostEqual(crypto.net_return, 0.0050)

    def test_fee_config_loads_playbook_asset_class_rules(self) -> None:
        rules = load_fee_rules()

        self.assertEqual(rules["india_equity"].fee_rate, 0.0012)
        self.assertEqual(rules["india_equity"].slippage_rate, 0.0005)
        self.assertEqual(rules["crypto"].fee_rate, 0.0010)
        self.assertEqual(rules["crypto"].slippage_rate, 0.0015)

    def test_walk_forward_windows_are_non_overlapping_oos_slices(self) -> None:
        engine = BacktestEngine()

        windows = engine.walk_forward_windows(
            total_observations=12,
            train_size=5,
            test_size=2,
        )

        self.assertEqual(
            [(window.train_start, window.train_end, window.test_start, window.test_end) for window in windows],
            [(0, 5, 5, 7), (2, 7, 7, 9), (4, 9, 9, 11)],
        )
        self.assertTrue(all(window.train_end == window.test_start for window in windows))

    def test_out_of_sample_evaluation_runs_test_windows_only(self) -> None:
        engine = BacktestEngine(
            fee_rules={"test": FeeRule("test", fee_rate=0.0, slippage_rate=0.0)}
        )
        signals = [signal(index, asset_class="test", gross_return=0.01) for index in range(8)]

        results = engine.evaluate_out_of_sample(signals, train_size=4, test_size=2)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.metadata["out_of_sample"] for result in results))
        self.assertTrue(all(result.stats.observations == 2 for result in results))

    def test_zero_volatility_edge_cases_do_not_divide_by_zero(self) -> None:
        engine = BacktestEngine(trading_periods_per_year=4)

        stats = engine.calculate_stats([0.01, 0.01, 0.01, 0.01])

        self.assertEqual(stats.volatility, 0.0)
        self.assertEqual(stats.sharpe, 0.0)
        self.assertEqual(stats.sortino, 0.0)
        self.assertEqual(stats.max_drawdown, 0.0)

    def test_brier_score_and_feast_offline_store_hook(self) -> None:
        engine = BacktestEngine()
        stats = engine.calculate_stats(
            [0.01, -0.01],
            forecast_probabilities=[0.8, 0.2],
            realized_outcomes=[1, 0],
        )
        store = FakeOfflineStore()

        payload = engine.fetch_feast_offline_features(
            store,
            features=["daily_market_metrics:close"],
            entity_df=[{"asset_id": "NIFTY_50"}],
        )

        self.assertAlmostEqual(stats.brier_score or 0.0, 0.04)
        self.assertEqual(payload, {"features": ["daily_market_metrics:close"]})
        self.assertEqual(store.calls, 1)


def signal(index: int, *, asset_class: str, gross_return: float) -> TradeSignal:
    return TradeSignal(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
        asset_id="UNIT",
        asset_class=asset_class,
        gross_return=gross_return,
    )


class FakeOfflineStore:
    def __init__(self) -> None:
        self.calls = 0

    def get_historical_features(self, *, features: list[str], entity_df: object) -> dict[str, list[str]]:
        self.calls += 1
        return {"features": features}


if __name__ == "__main__":
    unittest.main()
