from __future__ import annotations

import unittest
from datetime import datetime, timezone

from analytics.diagnostics.crypto_intelligence import (
    CRYPTO_NARRATIVES,
    TRANSITION_STATES,
    CryptoIntelligenceEngine,
    CryptoNarrativeInput,
    coinbase_premium,
    cumulative_volume_delta,
    from_market_rows,
    stablecoin_growth_rate,
    stablecoin_velocity,
)


class Phase15CryptoIntelligenceTest(unittest.TestCase):
    def test_all_required_narratives_are_supported(self) -> None:
        engine = CryptoIntelligenceEngine()

        self.assertEqual(len(engine.narratives), 12)
        self.assertEqual(set(engine.narratives), set(CRYPTO_NARRATIVES))

    def test_narrative_metrics_are_bounded(self) -> None:
        metric = CryptoIntelligenceEngine().score_narrative(bullish_input("BTC"))

        self.assertEqual(metric.narrative, "BTC")
        self.assert_score(metric.narrative_health)
        self.assert_score(metric.stress_score)
        self.assert_score(metric.rotation_score)
        self.assertTrue(0.0 <= metric.crash_probability <= 1.0)
        self.assertTrue(0.0 <= metric.pump_probability <= 1.0)
        self.assertTrue(0.0 <= metric.expected_drawdown <= 1.0)
        self.assertTrue(0.0 <= metric.expected_upside <= 1.0)
        self.assert_score(metric.early_warning_score)
        self.assert_score(metric.funding_stress)

    def test_stress_increases_for_weak_narrative_inputs(self) -> None:
        engine = CryptoIntelligenceEngine()
        healthy = engine.score_narrative(bullish_input("ETH"))
        stressed = engine.score_narrative(stressed_input("ETH"))

        self.assertGreater(stressed.stress_score, healthy.stress_score)
        self.assertGreater(stressed.crash_probability, healthy.crash_probability)
        self.assertLess(stressed.narrative_health, healthy.narrative_health)

    def test_cvd_processes_order_book_sign_changes(self) -> None:
        self.assertEqual(cumulative_volume_delta(700.0, 300.0), 400.0)
        self.assertEqual(cumulative_volume_delta(250.0, 600.0), -350.0)
        self.assertEqual(cumulative_volume_delta(None, 600.0), -600.0)

    def test_stablecoin_velocity_handles_zero_supply(self) -> None:
        self.assertEqual(stablecoin_velocity(1000.0, 0.0), 0.0)
        self.assertEqual(stablecoin_velocity(1000.0, None), 0.0)
        self.assertAlmostEqual(stablecoin_velocity(500.0, 1000.0), 0.5)

    def test_stablecoin_growth_and_coinbase_premium(self) -> None:
        self.assertAlmostEqual(stablecoin_growth_rate(1100.0, 1000.0), 0.1)
        self.assertEqual(stablecoin_growth_rate(1100.0, 0.0), 0.0)
        self.assertAlmostEqual(coinbase_premium(101.0, 100.0), 0.01)
        self.assertEqual(coinbase_premium(101.0, 0.0), 0.0)

    def test_score_all_handles_missing_narratives(self) -> None:
        metrics = CryptoIntelligenceEngine().score_all([bullish_input("SOL")])

        self.assertEqual(set(metrics), set(CRYPTO_NARRATIVES))
        for metric in metrics.values():
            self.assert_score(metric.narrative_health)
            self.assert_score(metric.early_warning_score)
            self.assertTrue(0.0 <= metric.crash_probability <= 1.0)

    def test_narrative_similarity_is_bounded(self) -> None:
        engine = CryptoIntelligenceEngine()
        history = [engine.score_narrative(bullish_input("AI"))]

        similar = engine.score_narrative(bullish_input("AI"), historical_metrics=history)
        different = engine.score_narrative(stressed_input("AI"), historical_metrics=history)

        self.assert_score(similar.narrative_similarity_score)
        self.assertGreater(similar.narrative_similarity_score, different.narrative_similarity_score)

    def test_transition_matrix_rows_sum_to_one(self) -> None:
        engine = CryptoIntelligenceEngine()
        metrics = [engine.score_narrative(bullish_input("BTC")), engine.score_narrative(stressed_input("MEMES"))]
        matrix = engine.transition_matrix(metrics)

        self.assertEqual(set(matrix), set(TRANSITION_STATES))
        for row in matrix.values():
            self.assertEqual(set(row), set(TRANSITION_STATES))
            self.assertAlmostEqual(sum(row.values()), 1.0)
            self.assertTrue(all(0.0 <= value <= 1.0 for value in row.values()))

    def test_market_row_conversion_hook(self) -> None:
        rows = [
            {
                "event_timestamp": "2026-01-01T00:00:00+00:00",
                "narrative": "DeFi",
                "market_cap": 1000.0,
                "previous_market_cap": 900.0,
                "buy_volume": 300.0,
                "sell_volume": 100.0,
            }
        ]

        inputs = from_market_rows(rows)

        self.assertEqual(inputs[0].narrative, "DeFi")
        self.assertEqual(inputs[0].market_cap, 1000.0)

    def assert_score(self, value: float) -> None:
        self.assertTrue(0.0 <= value <= 100.0)


def bullish_input(narrative: str) -> CryptoNarrativeInput:
    return CryptoNarrativeInput(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        narrative=narrative,
        market_cap=1200.0,
        previous_market_cap=1000.0,
        volume=800.0,
        previous_volume=650.0,
        coinbase_price=101.0,
        global_spot_price=100.0,
        etf_inflow=500.0,
        exchange_inflow=-100.0,
        funding_rate=0.005,
        open_interest=1100.0,
        previous_open_interest=1000.0,
        stablecoin_supply=11000.0,
        previous_stablecoin_supply=10000.0,
        buy_volume=600.0,
        sell_volume=250.0,
    )


def stressed_input(narrative: str) -> CryptoNarrativeInput:
    return CryptoNarrativeInput(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        narrative=narrative,
        market_cap=750.0,
        previous_market_cap=1000.0,
        volume=400.0,
        previous_volume=800.0,
        coinbase_price=97.0,
        global_spot_price=100.0,
        etf_inflow=-300.0,
        exchange_inflow=900.0,
        funding_rate=0.06,
        open_interest=1500.0,
        previous_open_interest=1000.0,
        stablecoin_supply=9000.0,
        previous_stablecoin_supply=10000.0,
        buy_volume=200.0,
        sell_volume=850.0,
    )


if __name__ == "__main__":
    unittest.main()
