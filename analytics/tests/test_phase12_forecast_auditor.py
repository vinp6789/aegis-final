from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from analytics.governance.forecast_auditor import (
    ForecastAuditExceptionPersistenceAdapter,
    ForecastAuditor,
    ForecastRecord,
    baseline_brier_score,
    brier_score,
    brier_skill_score,
    expected_calibration_error,
    forecast_drift,
    records_from_probability_rows,
)


class Phase12ForecastAuditorTest(unittest.TestCase):
    def test_brier_and_brier_skill_score(self) -> None:
        probabilities = [0.1, 0.2, 0.8, 0.9]
        outcomes = [0, 0, 1, 1]

        model_brier = brier_score(probabilities, outcomes)
        baseline = baseline_brier_score(outcomes)

        self.assertAlmostEqual(model_brier, 0.025)
        self.assertAlmostEqual(baseline, 0.25)
        self.assertAlmostEqual(brier_skill_score(model_brier, baseline), 0.9)

    def test_expected_calibration_error_is_bounded(self) -> None:
        ece = expected_calibration_error(
            [0.05, 0.15, 0.85, 0.95],
            [0, 0, 1, 1],
            bins=5,
        )

        self.assertTrue(0.0 <= ece <= 1.0)
        self.assertLess(ece, 0.15)

    def test_forecast_drift_detects_distribution_shift(self) -> None:
        records = [
            forecast_record(day=day, probability=0.15)
            for day in range(30)
        ] + [
            forecast_record(day=day, probability=0.75)
            for day in range(30, 60)
        ]

        self.assertGreater(forecast_drift(records, days=30), 0.50)
        self.assertTrue(0.0 <= forecast_drift(records, days=7) <= 1.0)

    def test_audit_loop_handles_missing_values_safely(self) -> None:
        auditor = ForecastAuditor(drift_threshold=0.10, brier_threshold=0.18)
        records = [
            forecast_record(day=0, probability=None, outcome=1),
            forecast_record(day=1, probability=1.5, outcome=1),
            forecast_record(day=2, probability=-0.5, outcome=0),
            forecast_record(day=3, probability=0.25, outcome=None),
        ]

        result = auditor.audit(records)

        self.assertEqual(result.metrics.resolved_count, 3)
        self.assertEqual(result.metrics.unresolved_count, 1)
        self.assertTrue(0.0 <= result.metrics.brier_score <= 1.0)
        self.assertTrue(-1.0 <= result.metrics.brier_skill_score <= 1.0)
        self.assertTrue(0.0 <= result.metrics.expected_calibration_error <= 1.0)

    def test_persistence_adapter_targets_existing_exception_table(self) -> None:
        auditor = ForecastAuditor(drift_threshold=0.10, brier_threshold=0.18)
        adapter = ForecastAuditExceptionPersistenceAdapter()
        result = auditor.audit([forecast_record(day=0, probability=0.9, outcome=0)])
        row = adapter.to_row(result)

        self.assertEqual(adapter.table_name, "data_quality_exceptions")
        self.assertEqual(row["source_name"], "forecast_auditor")
        self.assertIn(row["severity"], {"LOW", "MEDIUM", "CRITICAL"})
        payload = json.loads(row["bad_value_raw"])
        self.assertIn("brier_score", payload["metrics"])

    def test_audit_and_persist_executes_insert(self) -> None:
        auditor = ForecastAuditor()
        connection = FakeConnection()

        result = auditor.audit_and_persist(
            connection,
            [forecast_record(day=0, probability=0.2, outcome=0)],
            repository=ForecastAuditExceptionPersistenceAdapter(),
        )

        sql, params = connection.cursor_obj.executed[0]
        self.assertIn("INSERT INTO data_quality_exceptions", sql)
        self.assertEqual(params[1], "forecast_auditor")
        self.assertEqual(result.metrics.resolved_count, 1)

    def test_probability_rows_convert_to_audit_records(self) -> None:
        rows = [
            {
                "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "target_scope": "GLOBAL",
                "crash_prob_12m": 0.42,
                "realized_outcome": 1,
            }
        ]

        records = records_from_probability_rows(rows, horizon_months=12)

        self.assertEqual(records[0].probability, 0.42)
        self.assertEqual(records[0].realized_outcome, 1)
        self.assertEqual(records[0].forecast_type, "systemic_stress")


def forecast_record(
    *,
    day: int,
    probability: float | None,
    outcome: int | None = 0,
) -> ForecastRecord:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    return ForecastRecord(
        timestamp=timestamp,
        target_scope="GLOBAL",
        forecast_type="systemic_stress",
        horizon_months=12,
        probability=probability,
        realized_outcome=outcome,
        resolved_timestamp=timestamp + timedelta(days=365),
    )


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
