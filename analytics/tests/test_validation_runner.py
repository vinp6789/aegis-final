from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from analytics.validation.calibration import (
    BetaCalibrator,
    IsotonicScaler,
    PlattScaler,
    brier_score,
    evaluate_calibration,
    expected_calibration_error,
)
from analytics.validation.splitter import (
    PurgedEmbargoedKFoldSplitter,
    expanding_walk_forward_split,
    rolling_walk_forward_split,
)


class Phase6ValidationRunnerTest(unittest.TestCase):
    def test_rolling_walk_forward_split_integrity_and_no_overlap(self) -> None:
        timestamps = daily_history(240)

        splits = rolling_walk_forward_split(
            timestamps,
            train_size=80,
            test_size=20,
            step_size=20,
            embargo_days=60,
        )

        self.assertTrue(splits)
        for split in splits:
            self.assertFalse(split.has_overlap)
            self.assertEqual(split.train_indices[-1] + 60, split.test_indices[0])
            self.assertGreaterEqual((split.test_start - split.train_end).days, 60)

    def test_expanding_window_grows_training_window(self) -> None:
        timestamps = daily_history(240)

        splits = expanding_walk_forward_split(
            timestamps,
            train_size=60,
            test_size=20,
            step_size=20,
            embargo_days=60,
        )

        self.assertGreaterEqual(len(splits), 3)
        train_lengths = [len(split.train_indices) for split in splits]
        self.assertEqual(train_lengths, sorted(train_lengths))
        self.assertGreater(train_lengths[-1], train_lengths[0])
        self.assertTrue(all(not split.has_overlap for split in splits))

    def test_purged_embargoed_kfold_protects_overlap(self) -> None:
        timestamps = daily_history(360)

        splits = PurgedEmbargoedKFoldSplitter(n_splits=4, embargo_days=60).split(timestamps)

        self.assertEqual(len(splits), 4)
        for split in splits:
            self.assertFalse(split.has_overlap)
            train_set = set(split.train_indices)
            for test_index in split.test_indices:
                forbidden = range(max(0, test_index - 60), min(len(timestamps), test_index + 61))
                self.assertTrue(train_set.isdisjoint(forbidden))

    def test_calibration_outputs_are_probability_bounded(self) -> None:
        scores = [-3.0, -1.5, -0.2, 0.4, 1.1, 2.5, 3.2]
        outcomes = [0, 0, 0, 1, 1, 1, 1]

        platt = PlattScaler(iterations=300).fit(scores, outcomes).predict(scores)
        isotonic = IsotonicScaler().fit(scores, outcomes).predict(scores)
        beta = BetaCalibrator().fit([0.05, 0.2, 0.4, 0.7, 0.9], [0, 0, 1, 1, 1]).predict(
            [-0.2, 0.1, 0.5, 1.2]
        )

        for values in (platt, isotonic, beta):
            self.assertTrue(all(0.0 <= value <= 1.0 for value in values))
        self.assertEqual(isotonic, sorted(isotonic))

    def test_calibration_metrics_include_brier_and_ece(self) -> None:
        probabilities = [0.1, 0.2, 0.8, 0.9]
        outcomes = [0, 0, 1, 1]

        metrics = evaluate_calibration(probabilities, outcomes)

        self.assertEqual(metrics.brier_score, brier_score(probabilities, outcomes))
        self.assertEqual(
            metrics.expected_calibration_error,
            expected_calibration_error(probabilities, outcomes),
        )
        self.assertLess(metrics.brier_score, 0.05)
        self.assertGreaterEqual(metrics.expected_calibration_error, 0.0)

    def test_real_historical_sample_execution(self) -> None:
        timestamps = daily_history(180)
        historical_returns = [
            0.01 if index % 9 in {0, 1, 2, 3, 4} else -0.004
            for index in range(len(timestamps))
        ]

        splits = rolling_walk_forward_split(
            timestamps,
            train_size=60,
            test_size=15,
            step_size=15,
            embargo_days=60,
        )

        self.assertTrue(splits)
        for split in splits:
            train_returns = [historical_returns[index] for index in split.train_indices]
            test_returns = [historical_returns[index] for index in split.test_indices]
            self.assertTrue(train_returns)
            self.assertTrue(test_returns)
            self.assertFalse(split.has_overlap)
            self.assertGreaterEqual((split.test_start - split.train_end).days, 60)


def daily_history(length: int) -> list[datetime]:
    start = datetime(2020, 1, 1)
    return [start + timedelta(days=index) for index in range(length)]


if __name__ == "__main__":
    unittest.main()
