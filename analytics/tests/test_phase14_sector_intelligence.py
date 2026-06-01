from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from analytics.diagnostics.sector_intelligence import (
    INDIA_SECTORS,
    ROLLING_WINDOWS,
    IndiaSectorIntelligenceEngine,
    SectorInput,
    cosine_similarity,
    from_feast_rows,
    rolling_outcome,
)


class Phase14SectorIntelligenceTest(unittest.TestCase):
    def test_all_16_sector_keys_are_supported(self) -> None:
        engine = IndiaSectorIntelligenceEngine()

        self.assertEqual(len(engine.sectors), 16)
        self.assertEqual(set(engine.sectors), set(INDIA_SECTORS))

    def test_sector_health_scoring_outputs_are_bounded(self) -> None:
        metric = IndiaSectorIntelligenceEngine().score_sector(bullish_input("BANKING"))

        self.assertEqual(metric.sector, "BANKING")
        self.assert_bounded_score(metric.sector_health_score)
        self.assert_bounded_score(metric.stress_score)
        self.assert_bounded_score(metric.expansion_score)
        self.assert_bounded_score(metric.rotation_score)
        self.assertTrue(0.0 <= metric.expected_drawdown <= 1.0)
        self.assertTrue(0.0 <= metric.expected_upside <= 1.0)
        self.assertTrue(0.0 <= metric.crash_probability <= 1.0)
        self.assert_bounded_score(metric.early_warning_score)

    def test_stress_metrics_increase_for_weak_sector_inputs(self) -> None:
        engine = IndiaSectorIntelligenceEngine()
        healthy = engine.score_sector(bullish_input("AUTO"))
        stressed = engine.score_sector(stressed_input("AUTO"))

        self.assertGreater(stressed.stress_score, healthy.stress_score)
        self.assertGreater(stressed.crash_probability, healthy.crash_probability)
        self.assertLess(stressed.sector_health_score, healthy.sector_health_score)

    def test_score_all_returns_metrics_for_all_sectors_with_missing_inputs(self) -> None:
        metrics = IndiaSectorIntelligenceEngine().score_all([bullish_input("IT")])

        self.assertEqual(set(metrics), set(INDIA_SECTORS))
        self.assertEqual(metrics["IT"].sector, "IT")
        for metric in metrics.values():
            self.assert_bounded_score(metric.sector_health_score)
            self.assert_bounded_score(metric.early_warning_score)

    def test_similarity_and_novelty_scores_are_bounded(self) -> None:
        engine = IndiaSectorIntelligenceEngine()
        history = [engine.score_sector(bullish_input("PHARMA"))]

        similar = engine.score_sector(bullish_input("PHARMA"), historical_metrics=history)
        different = engine.score_sector(stressed_input("PHARMA"), historical_metrics=history)

        self.assert_bounded_score(similar.sector_similarity_score)
        self.assert_bounded_score(similar.sector_novelty_score)
        self.assertGreater(similar.sector_similarity_score, different.sector_similarity_score)
        self.assertLess(similar.sector_novelty_score, different.sector_novelty_score)

    def test_rolling_outcomes_cover_required_windows_and_empty_history(self) -> None:
        engine = IndiaSectorIntelligenceEngine()

        empty = engine.rolling_outcomes([])
        self.assertEqual(set(empty["BANKING"]), set(ROLLING_WINDOWS))
        self.assertEqual(empty["BANKING"][30].observations, 0)

        history = [
            SectorInput(
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day),
                sector="BANKING",
                close=100.0 + day,
            )
            for day in range(40)
        ]
        outcomes = engine.rolling_outcomes(history)

        self.assertGreater(outcomes["BANKING"][30].realized_return, 0.0)
        self.assertEqual(outcomes["BANKING"][30].observations, 30)

    def test_drawdown_model_handles_empty_history_safely(self) -> None:
        outcome = rolling_outcome("BANKING", [], 30)

        self.assertEqual(outcome.realized_return, 0.0)
        self.assertEqual(outcome.max_drawdown, 0.0)
        self.assertEqual(outcome.max_upside, 0.0)

    def test_feast_row_conversion_hook(self) -> None:
        rows = [
            {
                "event_timestamp": "2026-01-01T00:00:00+00:00",
                "sector_name": "Capital Goods",
                "close": 120.0,
                "previous_close": 118.0,
                "fii_flow": 100.0,
                "dii_flow": 50.0,
            }
        ]

        inputs = from_feast_rows(rows)

        self.assertEqual(inputs[0].sector, "Capital Goods")
        self.assertEqual(inputs[0].close, 120.0)

    def test_cosine_similarity_bounds(self) -> None:
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 0.0]), 0.0)

    def assert_bounded_score(self, value: float) -> None:
        self.assertTrue(0.0 <= value <= 100.0)


def bullish_input(sector: str) -> SectorInput:
    return SectorInput(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        sector=sector,
        close=110.0,
        previous_close=100.0,
        market_cap=100000.0,
        sector_weight=0.08,
        fii_flow=400.0,
        dii_flow=250.0,
        liquidity_index=75.0,
        leading_diffusion_index=0.45,
        regime_probability=0.20,
        volatility_index=25.0,
        earnings_revision=0.20,
    )


def stressed_input(sector: str) -> SectorInput:
    return SectorInput(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        sector=sector,
        close=85.0,
        previous_close=100.0,
        market_cap=100000.0,
        sector_weight=0.03,
        fii_flow=-700.0,
        dii_flow=-200.0,
        liquidity_index=25.0,
        leading_diffusion_index=-0.65,
        regime_probability=0.85,
        volatility_index=80.0,
        earnings_revision=-0.30,
    )


if __name__ == "__main__":
    unittest.main()
