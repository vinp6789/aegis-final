from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from analytics.validation.forecast_outcomes import (
    ForecastOutcomeAuditPersistenceAdapter,
    ForecastOutcomeRecord,
    ForecastOutcomeValidator,
    adaptive_weight_audit,
    report_to_dict,
    rolling_validation_metrics,
)


class ForecastOutcomeValidatorTest(unittest.TestCase):
    def test_compares_forecasts_to_realized_outcomes(self) -> None:
        validator = ForecastOutcomeValidator()

        comparisons, unresolved = validator.compare(
            [
                outcome_record(day=0, probability=0.80, outcome=1),
                outcome_record(day=1, probability=0.20, outcome=0),
                outcome_record(day=2, probability=0.75, outcome=None),
            ]
        )

        self.assertEqual(len(comparisons), 2)
        self.assertEqual(unresolved, 1)
        self.assertTrue(all(comparison.correct for comparison in comparisons))
        self.assertLess(comparisons[0].squared_error, 0.05)

    def test_rolling_metrics_include_3m_6m_12m_windows(self) -> None:
        as_of = datetime(2026, 12, 31, tzinfo=timezone.utc)
        comparisons, _unresolved = ForecastOutcomeValidator().compare(
            [
                outcome_record(day=-20, probability=0.90, outcome=1, as_of=as_of),
                outcome_record(day=-40, probability=0.15, outcome=0, as_of=as_of),
                outcome_record(day=-130, probability=0.80, outcome=1, as_of=as_of),
                outcome_record(day=-250, probability=0.30, outcome=0, as_of=as_of),
            ]
        )

        metrics = rolling_validation_metrics(comparisons, as_of=as_of)

        self.assertEqual(set(metrics), {3, 6, 12})
        self.assertEqual(metrics[3].sample_count, 2)
        self.assertEqual(metrics[6].sample_count, 3)
        self.assertEqual(metrics[12].sample_count, 4)
        self.assertEqual(metrics[12].precision, 1.0)
        self.assertEqual(metrics[12].recall, 1.0)
        self.assertEqual(metrics[12].f1, 1.0)
        self.assertEqual(metrics[12].roc_auc, 1.0)
        self.assertLess(metrics[12].brier_score, 0.1)

    def test_roc_auc_is_none_when_only_one_class_is_present(self) -> None:
        as_of = datetime(2026, 12, 31, tzinfo=timezone.utc)
        report = ForecastOutcomeValidator().validate(
            [
                outcome_record(day=-10, probability=0.70, outcome=1, as_of=as_of),
                outcome_record(day=-20, probability=0.80, outcome=1, as_of=as_of),
            ],
            as_of=as_of,
        )

        self.assertIsNone(report.rolling_metrics["3M"].roc_auc)
        self.assertTrue(0.0 <= report.forecast_reliability_score <= 100.0)

    def test_reliability_trend_and_driver_attribution_are_reported(self) -> None:
        as_of = datetime(2026, 12, 31, tzinfo=timezone.utc)
        report = ForecastOutcomeValidator().validate(
            [
                outcome_record(day=-20, probability=0.90, outcome=1, as_of=as_of, liquidity=0.9, credit=0.2),
                outcome_record(day=-40, probability=0.10, outcome=0, as_of=as_of, liquidity=0.8, credit=0.1),
                outcome_record(day=-180, probability=0.85, outcome=0, as_of=as_of, liquidity=0.2, credit=0.9),
                outcome_record(day=-220, probability=0.20, outcome=1, as_of=as_of, liquidity=0.1, credit=0.8),
            ],
            as_of=as_of,
        )

        self.assertEqual(report.reliability_trend.direction, "IMPROVING")
        self.assertEqual(report.correct_forecast_drivers[0].factor, "liquidity")
        self.assertEqual(report.incorrect_forecast_drivers[0].factor, "credit")
        self.assertTrue(0.0 <= report.research_readiness_score <= 100.0)
        self.assertTrue(0.0 <= report.model_trust_score <= 100.0)

    def test_adaptive_weight_audit_recommends_without_mutating_production_weights(self) -> None:
        as_of = datetime(2026, 12, 31, tzinfo=timezone.utc)
        comparisons, _unresolved = ForecastOutcomeValidator().compare(
            [
                outcome_record(day=-20, probability=0.90, outcome=1, as_of=as_of, liquidity=0.9, credit=0.1),
                outcome_record(day=-40, probability=0.15, outcome=0, as_of=as_of, liquidity=0.8, credit=0.2),
                outcome_record(day=-70, probability=0.80, outcome=0, as_of=as_of, liquidity=0.1, credit=0.9),
            ]
        )

        recommendations = adaptive_weight_audit(comparisons)
        recommended_by_factor = {item.factor: item for item in recommendations}

        self.assertAlmostEqual(sum(item.recommended_weight for item in recommendations), 1.0)
        self.assertGreater(
            recommended_by_factor["liquidity"].recommended_weight,
            recommended_by_factor["credit"].recommended_weight,
        )
        self.assertEqual(recommended_by_factor["liquidity"].current_weight, 0.5)
        self.assertEqual(recommended_by_factor["credit"].current_weight, 0.5)

    def test_report_is_machine_readable_and_persisted_through_audit_table(self) -> None:
        as_of = datetime(2026, 12, 31, tzinfo=timezone.utc)
        validator = ForecastOutcomeValidator()
        connection = FakeConnection()
        adapter = ForecastOutcomeAuditPersistenceAdapter()

        report = validator.validate_and_persist(
            connection,
            [
                outcome_record(day=-20, probability=0.90, outcome=1, as_of=as_of),
                outcome_record(day=-40, probability=0.15, outcome=0, as_of=as_of),
            ],
            repository=adapter,
            as_of=as_of,
        )

        payload = report_to_dict(report)
        self.assertIn("rolling_metrics", payload)
        self.assertIn("adaptive_weight_recommendations", payload)
        sql, params = connection.cursor_obj.executed[0]
        self.assertIn("INSERT INTO data_quality_exceptions", sql)
        self.assertEqual(params[1], "forecast_outcomes")
        stored_payload = json.loads(params[4])
        self.assertIn("forecast_reliability_score", stored_payload)


def outcome_record(
    *,
    day: int,
    probability: float,
    outcome: int | None,
    as_of: datetime | None = None,
    liquidity: float = 0.6,
    credit: float = 0.4,
) -> ForecastOutcomeRecord:
    anchor = as_of or datetime(2026, 1, 1, tzinfo=timezone.utc)
    resolved = anchor + timedelta(days=day)
    return ForecastOutcomeRecord(
        timestamp=resolved - timedelta(days=365),
        resolved_timestamp=resolved,
        probability=probability,
        realized_outcome=outcome,
        factors={"liquidity": liquidity, "credit": credit},
        production_weights={"liquidity": 0.5, "credit": 0.5},
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
