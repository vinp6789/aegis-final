from __future__ import annotations

import unittest

from analytics.validation.model_validation import (
    ForecastValidationSample,
    backtest_classification_metrics,
    calculate_validation_scores,
    conservative_probability,
    conservative_score,
    model_inventory,
    validation_status_lists,
)


class ModelValidationTest(unittest.TestCase):
    def test_conservative_probability_shrinks_toward_neutral_when_immature(self) -> None:
        immature = conservative_probability(0.90, 0.0)
        mature = conservative_probability(0.90, 100.0)

        self.assertLess(immature, mature)
        self.assertGreater(immature, 0.50)
        self.assertEqual(mature, 0.90)

    def test_conservative_score_shrinks_extreme_decisions(self) -> None:
        self.assertLess(conservative_score(90.0, 0.0), 90.0)
        self.assertGreater(conservative_score(10.0, 0.0), 10.0)

    def test_validation_scores_are_bounded_and_separated(self) -> None:
        scores = calculate_validation_scores(
            data_completeness=80.0,
            model_confidence=70.0,
            forecast_history_count=20,
            mature_sample_count=5,
            crisis_coverage=65.0,
            walk_forward_score=55.0,
            crisis_replay_score=60.0,
            calibration_error=0.08,
        )

        for key in (
            "pipeline_health",
            "data_completeness",
            "model_confidence",
            "forecast_maturity",
            "historical_validation_coverage",
            "signal_quality",
            "forecast_reliability",
        ):
            self.assertTrue(0.0 <= scores[key] <= 100.0)

    def test_backtest_metrics_include_classification_statistics(self) -> None:
        metrics = backtest_classification_metrics(
            [
                ForecastValidationSample(0.80, 1, 3.0, 0.2),
                ForecastValidationSample(0.70, 1, 2.0, 0.1),
                ForecastValidationSample(0.30, 0, 0.0, 0.0),
                ForecastValidationSample(0.20, 0, 0.0, 0.0),
            ]
        )

        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall"], 1.0)
        self.assertEqual(metrics["roc_auc"], 1.0)
        self.assertLess(metrics["brier_score"], 0.1)

    def test_inventory_and_status_lists_are_populated(self) -> None:
        self.assertGreaterEqual(len(model_inventory()), 8)
        status = validation_status_lists()
        self.assertTrue(status["validated_models"])
        self.assertTrue(status["calibrated_models"])
        self.assertTrue(status["unvalidated_models"])
        self.assertTrue(status["overconfident_models"])


if __name__ == "__main__":
    unittest.main()
