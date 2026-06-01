from __future__ import annotations

import unittest
from datetime import datetime, timezone

from analytics.validation.crisis_replay import CrisisReplayEngine, ReplayObservation


class CrisisReplayEngineTest(unittest.TestCase):
    def test_replay_detects_2008_panic_and_recovery(self) -> None:
        observations = {
            "2007-2009 Global Financial Crisis": [
                ReplayObservation(
                    timestamp=datetime(2007, 8, 1, tzinfo=timezone.utc),
                    panic_probability=72.0,
                    recovery_probability=35.0,
                    buy_score=20.0,
                    sell_score=70.0,
                    expected_return=-0.12,
                    expected_drawdown=0.30,
                    realized_return=-0.35,
                    realized_drawdown=0.45,
                ),
                ReplayObservation(
                    timestamp=datetime(2009, 5, 1, tzinfo=timezone.utc),
                    panic_probability=35.0,
                    recovery_probability=74.0,
                    buy_score=68.0,
                    sell_score=18.0,
                    expected_return=0.18,
                    expected_drawdown=0.12,
                    realized_return=0.25,
                    realized_drawdown=0.08,
                ),
            ],
            "2020 Pandemic Shock": [
                ReplayObservation(
                    timestamp=datetime(2020, 2, 15, tzinfo=timezone.utc),
                    panic_probability=80.0,
                    recovery_probability=42.0,
                    buy_score=25.0,
                    sell_score=76.0,
                    expected_return=-0.10,
                    expected_drawdown=0.25,
                    realized_return=-0.20,
                    realized_drawdown=0.32,
                ),
                ReplayObservation(
                    timestamp=datetime(2020, 5, 15, tzinfo=timezone.utc),
                    panic_probability=40.0,
                    recovery_probability=70.0,
                    buy_score=65.0,
                    sell_score=20.0,
                    expected_return=0.15,
                    expected_drawdown=0.10,
                    realized_return=0.18,
                    realized_drawdown=0.06,
                ),
            ],
        }

        result = CrisisReplayEngine().replay(observations)

        self.assertGreaterEqual(result.crisis_detection_rate, 40.0)
        self.assertGreaterEqual(result.recovery_detection_rate, 40.0)
        self.assertTrue(0.0 <= result.signal_quality_score <= 100.0)

    def test_empty_replay_returns_neutral_bootstrap(self) -> None:
        result = CrisisReplayEngine().replay({})

        self.assertEqual(result.crisis_detection_rate, 50.0)
        self.assertEqual(result.signal_quality_score, 50.0)


if __name__ == "__main__":
    unittest.main()
