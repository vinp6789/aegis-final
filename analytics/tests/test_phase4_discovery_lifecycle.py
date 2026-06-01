from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from analytics.discovery.discovery_engine import (
    CandidateFeature,
    DiscoveryConfig,
    DiscoveryEngine,
    FeatureEvaluation,
)
from analytics.discovery.lifecycle_manager import (
    FeatureLifecycleRecord,
    FeatureLifecycleState,
    LifecycleManager,
)


class Phase4DiscoveryEngineTest(unittest.TestCase):
    def test_discovery_engine_scores_and_ranks_candidate_features(self) -> None:
        target_3m = [0.01, 0.02, 0.03, 0.02, 0.04, 0.05, 0.06, 0.05]
        target_6m = [0.02, 0.03, 0.04, 0.03, 0.05, 0.06, 0.07, 0.06]
        engine = DiscoveryEngine(
            DiscoveryConfig(
                horizons_months=(3, 6),
                primary_horizon_months=3,
                secondary_horizon_months=6,
                min_observations=6,
            )
        )

        result = engine.evaluate(
            candidates=[
                CandidateFeature(
                    feature_name="liquidity_impulse",
                    target_scope="GLOBAL",
                    values=[1.0, 2.0, 3.0, 2.5, 4.0, 5.0, 6.0, 5.5],
                ),
                CandidateFeature(
                    feature_name="flat_signal",
                    target_scope="GLOBAL",
                    values=[1.0] * 8,
                ),
            ],
            target_returns={3: target_3m, 6: target_6m},
            evaluated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
        )

        self.assertEqual([item.feature_name for item in result.evaluated_features], ["liquidity_impulse", "flat_signal"])
        self.assertGreater(result.evaluated_features[0].current_score, 80.0)
        self.assertLess(result.evaluated_features[1].current_score, 20.0)
        self.assertEqual(result.rejected_features, {})
        self.assertEqual(result.evaluated_features[0].primary_horizon_months, 3)
        self.assertEqual(result.evaluated_features[0].secondary_horizon_months, 6)

    def test_discovery_engine_rejects_missing_and_short_candidates(self) -> None:
        engine = DiscoveryEngine(
            DiscoveryConfig(
                horizons_months=(3,),
                primary_horizon_months=3,
                secondary_horizon_months=3,
                min_observations=6,
                max_missing_ratio=0.2,
            )
        )

        result = engine.evaluate(
            candidates=[
                CandidateFeature("mostly_missing", "GLOBAL", [None, None, 1.0, None, 2.0, None]),
                CandidateFeature("too_short", "GLOBAL", [1.0, 2.0, 3.0]),
            ],
            target_returns={3: [0.1, 0.2, 0.3, 0.2, 0.4, 0.5]},
            evaluated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
        )

        self.assertEqual(result.evaluated_features, [])
        self.assertIn("missing-value limit", result.rejected_features["mostly_missing"])
        self.assertIn("too few observations", result.rejected_features["too_short"])


class Phase4LifecycleManagerTest(unittest.TestCase):
    def test_lifecycle_manager_promotes_strong_feature(self) -> None:
        manager = LifecycleManager()
        evaluation = make_evaluation("liquidity_impulse", current_score=82.0, peak_score=84.0)

        decision = manager.decide(evaluation)

        self.assertIsNone(decision.previous_state)
        self.assertEqual(decision.record.current_state, FeatureLifecycleState.PROMOTED)
        self.assertEqual(decision.record.consecutive_monthly_failures, 0)
        self.assertEqual(decision.record.peak_score, 84.0)

    def test_lifecycle_manager_demotes_promoted_feature_after_score_drop(self) -> None:
        manager = LifecycleManager()
        previous = FeatureLifecycleRecord(
            feature_name="liquidity_impulse",
            current_state=FeatureLifecycleState.PROMOTED,
            target_scope="GLOBAL",
            primary_horizon_months=3,
            secondary_horizon_months=6,
            current_score=76.0,
            peak_score=88.0,
            last_evaluated=datetime(2026, 4, 27, tzinfo=timezone.utc),
        )
        evaluation = make_evaluation("liquidity_impulse", current_score=42.0, peak_score=42.0)

        decision = manager.decide(evaluation, previous)

        self.assertEqual(decision.previous_state, FeatureLifecycleState.PROMOTED)
        self.assertEqual(decision.record.current_state, FeatureLifecycleState.DEMOTED)
        self.assertEqual(decision.record.consecutive_monthly_failures, 1)
        self.assertEqual(decision.record.peak_score, 88.0)
        self.assertEqual(decision.record.demoted_at, evaluation.evaluated_at)

    def test_lifecycle_manager_retires_after_repeated_failures(self) -> None:
        manager = LifecycleManager()
        previous = FeatureLifecycleRecord(
            feature_name="weak_feature",
            current_state=FeatureLifecycleState.WATCH,
            target_scope="GLOBAL",
            primary_horizon_months=3,
            secondary_horizon_months=6,
            current_score=44.0,
            peak_score=58.0,
            last_evaluated=datetime(2026, 4, 27, tzinfo=timezone.utc),
            consecutive_monthly_failures=2,
        )

        decision = manager.decide(make_evaluation("weak_feature", current_score=35.0, peak_score=35.0), previous)

        self.assertEqual(decision.record.current_state, FeatureLifecycleState.RETIRED)
        self.assertEqual(decision.record.consecutive_monthly_failures, 3)
        self.assertIn("maximum consecutive", decision.record.retirement_reason or "")

    def test_lifecycle_manager_persists_registry_upsert(self) -> None:
        manager = LifecycleManager()
        connection = FakeConnection()
        decision = manager.decide(make_evaluation("liquidity_impulse", current_score=82.0, peak_score=84.0))

        manager.persist_decision(connection, decision)

        self.assertEqual(len(connection.statements), 1)
        sql, values = connection.statements[0]
        self.assertIn("INSERT INTO feature_lifecycle_registry", sql)
        self.assertIn("ON CONFLICT (feature_name) DO UPDATE", sql)
        self.assertEqual(values[0], "liquidity_impulse")
        self.assertEqual(values[1], "PROMOTED")
        self.assertEqual(values[2], "GLOBAL")
        self.assertEqual(values[3], 3)
        self.assertEqual(values[4], 6)


def make_evaluation(feature_name: str, *, current_score: float, peak_score: float) -> FeatureEvaluation:
    return FeatureEvaluation(
        feature_name=feature_name,
        target_scope="GLOBAL",
        primary_horizon_months=3,
        secondary_horizon_months=6,
        current_score=current_score,
        peak_score=peak_score,
        evaluated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
        horizon_scores={},
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
