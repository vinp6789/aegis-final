from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from analytics.governance.governance_engine import (
    GovernanceEngine,
    GovernancePersistenceAdapter,
    ModelErrorProfile,
    apply_health_attenuation,
    consecutive_bad_bss,
    is_cooldown_active,
    population_stability_index,
)


class Phase13GovernanceEngineTest(unittest.TestCase):
    def test_population_stability_index_detects_drift(self) -> None:
        expected = [0.10, 0.12, 0.11, 0.13, 0.14, 0.15]
        actual = [0.70, 0.72, 0.74, 0.76, 0.78, 0.80]

        psi = population_stability_index(expected, actual, bins=5)

        self.assertGreaterEqual(psi, 0.25)
        self.assertTrue(0.0 <= psi <= 10.0)

    def test_retraining_trigger_locks_outputs_at_critical_psi(self) -> None:
        decision = GovernanceEngine().retraining_decision(
            psi=0.26,
            brier_skill_history=[0.2, 0.1],
            as_of=datetime(2026, 1, 31, tzinfo=timezone.utc),
        )

        self.assertTrue(decision.lock_outputs)
        self.assertTrue(decision.retraining_required)
        self.assertEqual(decision.reason, "PSI_CRITICAL")

    def test_retraining_cooldown_prevents_loop(self) -> None:
        as_of = datetime(2026, 1, 31, tzinfo=timezone.utc)
        last_retraining = as_of - timedelta(days=10)

        decision = GovernanceEngine().retraining_decision(
            psi=0.40,
            brier_skill_history=[-0.1, -0.2, -0.3, -0.4, -0.5],
            as_of=as_of,
            last_retraining_at=last_retraining,
        )

        self.assertTrue(is_cooldown_active(as_of, last_retraining, cooldown_days=30))
        self.assertTrue(decision.lock_outputs)
        self.assertFalse(decision.retraining_required)
        self.assertEqual(decision.reason, "COOLDOWN_ACTIVE")

    def test_bss_bad_streak_counts_trailing_failures(self) -> None:
        self.assertEqual(consecutive_bad_bss([0.2, -0.1, -0.2, -0.3]), 3)
        self.assertEqual(consecutive_bad_bss([-0.1, -0.2, 0.1]), 0)

    def test_weight_optimizer_enforces_cycle_weight_cap_and_sum(self) -> None:
        allocation = GovernanceEngine().optimize_weights(
            [
                ModelErrorProfile("cycle", [0.01, 0.01, 0.01], is_cycle_engine=True),
                ModelErrorProfile("liquidity", [0.20, 0.21, 0.19]),
                ModelErrorProfile("breadth", [0.25, 0.24, 0.26]),
            ]
        )

        self.assertLessEqual(allocation.weights["cycle"], 0.10)
        self.assertAlmostEqual(sum(allocation.weights.values()), 1.0)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in allocation.weights.values()))

    def test_health_attenuation_downweights_degraded_sources(self) -> None:
        base = {"healthy": 0.5, "degraded": 0.5}
        adjusted = apply_health_attenuation(
            base,
            [
                ModelErrorProfile("healthy", [0.2], source_health_score=95),
                ModelErrorProfile("degraded", [0.2], source_health_score=35),
            ],
            health_threshold=70,
        )

        self.assertLess(adjusted["degraded"], base["degraded"])
        self.assertAlmostEqual(sum(adjusted.values()), 1.0)

    def test_full_governance_run_handles_missing_values_safely(self) -> None:
        run = GovernanceEngine().run(
            expected_feature_distribution=[0.1, None, 0.2, 0.3],
            actual_feature_distribution=[0.1, 0.2, None, 0.4],
            model_profiles=[
                ModelErrorProfile("cycle", [None, 0.2], None, True),
                ModelErrorProfile("probability", [0.1, None], 100),
            ],
            brier_skill_history=[None, 0.1],
            as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        self.assertTrue(0.0 <= run.decision.psi <= 10.0)
        self.assertAlmostEqual(sum(run.allocation.weights.values()), 1.0)
        self.assertLessEqual(run.allocation.weights["cycle"], 0.10)

    def test_persistence_adapter_uses_existing_exception_table(self) -> None:
        engine = GovernanceEngine()
        run = engine.run(
            expected_feature_distribution=[0.1, 0.2, 0.3],
            actual_feature_distribution=[0.7, 0.8, 0.9],
            model_profiles=[ModelErrorProfile("probability", [0.2, 0.3])],
            brier_skill_history=[0.1],
            as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        adapter = GovernancePersistenceAdapter()
        row = adapter.to_row(run)

        self.assertEqual(adapter.table_name, "data_quality_exceptions")
        self.assertEqual(row["source_name"], "governance_engine")
        payload = json.loads(row["bad_value_raw"])
        self.assertIn("weights", payload)
        self.assertIn(row["severity"], {"LOW", "MEDIUM", "CRITICAL"})

    def test_persist_run_executes_insert(self) -> None:
        connection = FakeConnection()
        engine = GovernanceEngine()
        run = engine.run(
            expected_feature_distribution=[0.1, 0.2, 0.3],
            actual_feature_distribution=[0.1, 0.2, 0.3],
            model_profiles=[ModelErrorProfile("probability", [0.2])],
            brier_skill_history=[0.1],
            as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        engine.persist_run(connection, run)

        sql, params = connection.cursor_obj.executed[0]
        self.assertIn("INSERT INTO data_quality_exceptions", sql)
        self.assertEqual(params[1], "governance_engine")


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()

    def cursor(self) -> "FakeCursor":
        return self.cursor_obj


class FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executed.append((sql, params))


if __name__ == "__main__":
    unittest.main()
