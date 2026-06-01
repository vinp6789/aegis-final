from __future__ import annotations

import math
import unittest
from datetime import datetime, timezone
from typing import Any

from analytics.discovery.discovery_engine import CandidateFeature, DiscoveryConfig, DiscoveryEngine
from analytics.discovery.lifecycle_manager import (
    FeatureLifecycleRecord,
    FeatureLifecycleState,
    LifecycleManager,
)


class Phase4DiscoveryRunnerTest(unittest.TestCase):
    def test_correlated_synthetic_series_passes_granger_and_transfer_entropy(self) -> None:
        feature, target = leading_indicator_series()
        engine = DiscoveryEngine(
            DiscoveryConfig(
                horizons_months=(3,),
                primary_horizon_months=3,
                secondary_horizon_months=3,
                min_observations=30,
                granger_lag=2,
                transfer_entropy_threshold=0.01,
            )
        )

        result = engine.evaluate(
            candidates=[CandidateFeature("synthetic_leader", "GLOBAL", feature)],
            target_returns={3: target},
            evaluated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
        )

        self.assertEqual(result.rejected_features, {})
        evaluation = result.evaluated_features[0]
        primary = evaluation.primary_horizon
        self.assertIsNotNone(primary)
        self.assertTrue(primary.granger.causes_target)  # type: ignore[union-attr]
        self.assertLess(primary.granger.p_value, 0.05)  # type: ignore[union-attr]
        self.assertTrue(primary.transfer_entropy.exceeds_threshold)  # type: ignore[union-attr]
        self.assertGreater(primary.transfer_entropy.entropy, 0.01)  # type: ignore[union-attr]

    def test_uncorrelated_synthetic_series_does_not_pass_granger_threshold(self) -> None:
        feature = [math.sin(index * 0.41) for index in range(90)]
        target = [math.cos(index * 0.17) for index in range(90)]
        engine = DiscoveryEngine(
            DiscoveryConfig(
                horizons_months=(3,),
                primary_horizon_months=3,
                secondary_horizon_months=3,
                min_observations=30,
                granger_lag=2,
                transfer_entropy_threshold=0.01,
            )
        )

        evaluation = engine.evaluate(
            candidates=[CandidateFeature("uncorrelated_signal", "GLOBAL", feature)],
            target_returns={3: target},
        ).evaluated_features[0]

        primary = evaluation.primary_horizon
        self.assertIsNotNone(primary)
        self.assertFalse(primary.granger.causes_target)  # type: ignore[union-attr]
        self.assertGreaterEqual(primary.granger.p_value, 0.05)  # type: ignore[union-attr]

    def test_stationarity_transformation_differences_non_stationary_series(self) -> None:
        engine = DiscoveryEngine()
        trending = [index + math.sin(index / 3.0) for index in range(80)]

        stationarity = engine.stationarity_test(trending)

        self.assertTrue(stationarity.is_stationary)
        self.assertLess(len(stationarity.transformed_values), len(trending))

    def test_johansen_cointegration_flags_shared_trend(self) -> None:
        engine = DiscoveryEngine()
        left = [index + math.sin(index / 5.0) for index in range(80)]
        right = [2.0 * value + 0.5 for value in left]

        result = engine.johansen_cointegration_test(left, right)

        self.assertTrue(result.is_cointegrated)
        self.assertLess(result.p_value, 0.05)

    def test_lifecycle_transitions_follow_phase4_rules(self) -> None:
        feature, target = leading_indicator_series()
        engine = DiscoveryEngine(
            DiscoveryConfig(
                horizons_months=(3,),
                primary_horizon_months=3,
                secondary_horizon_months=3,
                min_observations=30,
                granger_lag=2,
                transfer_entropy_threshold=0.01,
            )
        )
        manager = LifecycleManager()
        evaluation = engine.evaluate(
            candidates=[CandidateFeature("synthetic_leader", "GLOBAL", feature)],
            target_returns={3: target},
            evaluated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
        ).evaluated_features[0]

        proposed_decision = manager.decide(evaluation)
        self.assertEqual(proposed_decision.record.current_state, FeatureLifecycleState.WATCH)

        watch_record = proposed_decision.record
        promoted_decision = manager.decide(
            replace_validation(evaluation, out_of_sample_validated=True),
            watch_record,
        )
        self.assertEqual(promoted_decision.record.current_state, FeatureLifecycleState.PROMOTED)

        record = promoted_decision.record
        deteriorating = replace_validation(evaluation, deterioration_detected=True, current_score=40.0)
        first_drop = manager.decide(deteriorating, record)
        second_drop = manager.decide(deteriorating, first_drop.record)
        third_drop = manager.decide(deteriorating, second_drop.record)

        self.assertEqual(first_drop.record.current_state, FeatureLifecycleState.DEMOTED)
        self.assertEqual(third_drop.record.current_state, FeatureLifecycleState.RETIRED)
        self.assertEqual(third_drop.record.consecutive_monthly_failures, 3)

    def test_lifecycle_registry_persistence_uses_feature_lifecycle_registry(self) -> None:
        feature, target = leading_indicator_series()
        engine = DiscoveryEngine(
            DiscoveryConfig(
                horizons_months=(3,),
                primary_horizon_months=3,
                secondary_horizon_months=3,
                min_observations=30,
                transfer_entropy_threshold=0.01,
            )
        )
        decision = LifecycleManager().decide(
            engine.evaluate(
                candidates=[CandidateFeature("synthetic_leader", "GLOBAL", feature)],
                target_returns={3: target},
            ).evaluated_features[0]
        )
        connection = FakeConnection()

        LifecycleManager().persist_decision(connection, decision)

        self.assertEqual(len(connection.statements), 1)
        sql, values = connection.statements[0]
        self.assertIn("INSERT INTO feature_lifecycle_registry", sql)
        self.assertIn("ON CONFLICT (feature_name) DO UPDATE", sql)
        self.assertEqual(values[0], "synthetic_leader")
        self.assertEqual(values[1], "WATCH")


def leading_indicator_series() -> tuple[list[float], list[float]]:
    feature = [math.sin(index / 4.0) + 0.03 * index for index in range(90)]
    target = [0.0, 0.0]
    for index in range(2, 90):
        target.append(0.55 * target[-1] + 0.9 * feature[index - 2] + 0.02 * math.sin(index))
    return feature, target


def replace_validation(
    evaluation: Any,
    *,
    out_of_sample_validated: bool | None = None,
    deterioration_detected: bool | None = None,
    current_score: float | None = None,
) -> Any:
    return type(evaluation)(
        feature_name=evaluation.feature_name,
        target_scope=evaluation.target_scope,
        primary_horizon_months=evaluation.primary_horizon_months,
        secondary_horizon_months=evaluation.secondary_horizon_months,
        current_score=evaluation.current_score if current_score is None else current_score,
        peak_score=evaluation.peak_score,
        evaluated_at=evaluation.evaluated_at,
        horizon_scores=evaluation.horizon_scores,
        out_of_sample_validated=(
            evaluation.out_of_sample_validated
            if out_of_sample_validated is None
            else out_of_sample_validated
        ),
        deterioration_detected=(
            evaluation.deterioration_detected
            if deterioration_detected is None
            else deterioration_detected
        ),
    )


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
