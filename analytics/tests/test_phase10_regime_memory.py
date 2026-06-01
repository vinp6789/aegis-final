from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from analytics.synthesis.regime_memory import (
    AnalogOutcome,
    HistoricalAnalog,
    RegimeFeatureVector,
    RegimeMemoryConfig,
    RegimeMemoryEngine,
    cosine_similarity,
    dynamic_time_warping,
    load_regime_config,
    time_decay_weight,
)


class Phase10RegimeMemoryTest(unittest.TestCase):
    def test_cosine_similarity_validation(self) -> None:
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_dtw_validation_and_output_matrix(self) -> None:
        self.assertEqual(dynamic_time_warping([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 0.0)
        self.assertGreater(dynamic_time_warping([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]), 0.0)

        engine = RegimeMemoryEngine(RegimeMemoryConfig(top_k=3))
        matrix_rows = engine.dtw_output_matrix(current_vector(), [analog("A", days_ago=5)])
        self.assertTrue(matrix_rows)
        self.assertEqual(len(matrix_rows[0]), len(current_vector().liquidity))
        self.assertAlmostEqual(matrix_rows[0][-1], 0.0)

    def test_analog_ranking_validation_returns_top_three(self) -> None:
        engine = RegimeMemoryEngine(RegimeMemoryConfig(top_k=3, decay_factor=1.0))
        history = [
            analog("BEST", days_ago=1),
            analog("MID", days_ago=1, liquidity=[70.0, 69.0, 68.0], regime_state="NEUTRAL"),
            analog("WEAK", days_ago=1, liquidity=[10.0, 12.0, 14.0], regime_state="CRISIS"),
            analog("FOURTH", days_ago=1, liquidity=[0.0, 0.0, 0.0], regime_state="RISK_OFF"),
        ]

        matches = engine.find_top_analogs(current_vector(), history)

        self.assertEqual(len(matches), 3)
        self.assertEqual(matches[0].analog_id, "BEST")
        self.assertGreaterEqual(matches[0].similarity_index, matches[1].similarity_index)
        self.assertTrue(all(0.0 <= match.similarity_index <= 100.0 for match in matches))
        self.assertEqual(matches[0].outcome.future_drawdown, -0.12)

    def test_decay_weighting_validation_discounts_older_analogs(self) -> None:
        current = now()
        recent = time_decay_weight(current, current - timedelta(days=63), 0.97, 63)
        older = time_decay_weight(current, current - timedelta(days=630), 0.97, 63)

        self.assertAlmostEqual(recent, 0.97)
        self.assertLess(older, recent)

    def test_historical_retrieval_validation(self) -> None:
        engine = RegimeMemoryEngine(RegimeMemoryConfig(top_k=3))
        store = FakeHistoricalStore()

        history = engine.retrieve_historical_analogs(store)

        self.assertEqual(store.calls, 1)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].analog_id, "ROW_A")
        self.assertEqual(history[0].outcome.sector_stress_outcome, 0.4)

    def test_missing_value_handling(self) -> None:
        engine = RegimeMemoryEngine(RegimeMemoryConfig(top_k=3))
        current = RegimeFeatureVector(
            timestamp=now(),
            liquidity=[75.0, None, 77.0],
            breadth=[0.2, None, 0.3],
            regime_state="RISK_ON",
            probability_vector=[0.1, None, 0.3],
        )

        match = engine.find_top_analogs(current, [analog("MISSING_SAFE", days_ago=1)])[0]

        self.assertTrue(0.0 <= match.similarity_index <= 100.0)

    def test_config_loads_playbook_parameters(self) -> None:
        config = load_regime_config()

        self.assertEqual(config.rolling_dtw_window_days, 63)
        self.assertEqual(config.decay_factor, 0.97)
        self.assertEqual(config.top_k, 3)


def now() -> datetime:
    return datetime(2026, 5, 27, tzinfo=timezone.utc)


def current_vector() -> RegimeFeatureVector:
    return RegimeFeatureVector(
        timestamp=now(),
        liquidity=[75.0, 76.0, 77.0],
        breadth=[0.2, 0.3, 0.4],
        regime_state="RISK_ON",
        probability_vector=[0.20, 0.30, 0.40, 0.50, 0.60],
    )


def analog(
    analog_id: str,
    *,
    days_ago: int,
    liquidity: list[float] | None = None,
    regime_state: str = "RISK_ON",
) -> HistoricalAnalog:
    return HistoricalAnalog(
        analog_id=analog_id,
        features=RegimeFeatureVector(
            timestamp=now() - timedelta(days=days_ago),
            liquidity=liquidity or [75.0, 76.0, 77.0],
            breadth=[0.2, 0.3, 0.4],
            regime_state=regime_state,
            probability_vector=[0.20, 0.30, 0.40, 0.50, 0.60],
        ),
        outcome=AnalogOutcome(
            future_drawdown=-0.12,
            future_volatility=0.24,
            liquidity_deterioration=0.18,
            sector_stress_outcome=0.35,
        ),
    )


class FakeHistoricalStore:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_regime_history(self, *, start: datetime | None = None, end: datetime | None = None) -> list[dict[str, Any]]:
        self.calls += 1
        return [
            {
                "analog_id": "ROW_A",
                "timestamp": now().isoformat(),
                "liquidity": [70.0, 71.0, 72.0],
                "breadth": [0.1, 0.2, 0.3],
                "regime_state": "NEUTRAL",
                "probability_vector": [0.2, 0.3, 0.4],
                "future_drawdown": -0.2,
                "future_volatility": 0.3,
                "liquidity_deterioration": 0.1,
                "sector_stress_outcome": 0.4,
            },
            {
                "analog_id": "ROW_B",
                "timestamp": (now() - timedelta(days=1)).isoformat(),
                "liquidity": [75.0, 76.0, 77.0],
                "breadth": [0.2, 0.3, 0.4],
                "regime_state": "RISK_ON",
                "probability_vector": [0.2, 0.3, 0.4],
                "future_drawdown": -0.1,
                "future_volatility": 0.2,
                "liquidity_deterioration": 0.05,
                "sector_stress_outcome": 0.2,
            },
        ]


if __name__ == "__main__":
    unittest.main()
