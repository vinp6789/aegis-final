from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from analytics.governance.explainability_engine import (
    ADDITIVE_TOLERANCE,
    ExplainabilityEngine,
    ExplainabilityPersistenceAdapter,
    FeatureVector,
)


class Phase16ExplainabilityEngineTest(unittest.TestCase):
    def test_shap_additive_property_is_verified(self) -> None:
        vector = feature_vector(prediction_value=0.62)
        explanation = ExplainabilityEngine().explain_from_shap_values(
            vector,
            base_value=0.40,
            shap_values={"liquidity": 0.12, "breadth": 0.08, "crypto": 0.02},
        )

        self.assertTrue(explanation.additive_valid)
        self.assertLessEqual(explanation.additive_error, ADDITIVE_TOLERANCE)
        self.assertAlmostEqual(
            explanation.base_value + sum(item.attribution for item in explanation.driver_attributions),
            explanation.prediction_value,
        )

    def test_additive_failure_is_flagged(self) -> None:
        vector = feature_vector(prediction_value=0.90)
        explanation = ExplainabilityEngine().explain_from_shap_values(
            vector,
            base_value=0.40,
            shap_values={"liquidity": 0.12, "breadth": 0.08, "crypto": 0.02},
        )

        self.assertFalse(explanation.additive_valid)
        self.assertGreater(explanation.additive_error, ADDITIVE_TOLERANCE)

    def test_driver_attribution_matrix_outputs_rows(self) -> None:
        engine = ExplainabilityEngine()
        explanation = engine.explain_from_shap_values(
            feature_vector(prediction_value=0.62),
            base_value=0.40,
            shap_values={"liquidity": 0.12, "breadth": 0.08, "crypto": 0.02},
        )

        matrix = engine.driver_attribution_matrix([explanation])

        self.assertEqual(len(matrix), 3)
        self.assertEqual(matrix[0]["feature_name"], "liquidity")
        self.assertTrue(0.0 <= matrix[0]["contribution_share"] <= 1.0)

    def test_forecast_to_forecast_diff_identifies_top_driver_shift(self) -> None:
        engine = ExplainabilityEngine()
        previous = engine.explain_from_shap_values(
            feature_vector(prediction_value=0.56, day=0),
            base_value=0.40,
            shap_values={"liquidity": 0.10, "breadth": 0.04, "crypto": 0.02},
        )
        current = engine.explain_from_shap_values(
            feature_vector(prediction_value=0.70, day=1),
            base_value=0.40,
            shap_values={"liquidity": 0.24, "breadth": 0.04, "crypto": 0.02},
        )

        diff = engine.forecast_diff(previous, current, top_n=2)

        self.assertAlmostEqual(diff.prediction_delta, 0.14)
        self.assertEqual(diff.top_driver_shifts[0].feature_name, "liquidity")
        self.assertEqual(len(diff.top_driver_shifts), 2)

    def test_model_provider_path_uses_background_reference(self) -> None:
        provider = FakeShapProvider(base_value=0.30, shap_values=[0.10, 0.05, 0.02])
        engine = ExplainabilityEngine(shap_provider=provider)

        explanation = engine.explain_model(
            object(),
            feature_vector(prediction_value=0.47),
            background=[{"liquidity": 40, "breadth": 0, "crypto": 45}],
        )

        self.assertTrue(explanation.additive_valid)
        self.assertEqual(provider.seen_background, [[0.0, 45.0, 40.0]])
        self.assertEqual(provider.seen_feature_names, ["breadth", "crypto", "liquidity"])

    def test_report_contains_primary_drivers_and_confidence(self) -> None:
        engine = ExplainabilityEngine()
        explanation = engine.explain_from_shap_values(
            feature_vector(prediction_value=0.62),
            base_value=0.40,
            shap_values={"liquidity": 0.12, "breadth": 0.08, "crypto": 0.02},
        )

        report = engine.explanation_report(explanation, analog_summaries=["2008 liquidity stress analog"])

        self.assertEqual(report.primary_drivers[:2], ["liquidity", "breadth"])
        self.assertIn("2008 liquidity stress analog", report.analog_summary)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in report.confidence_breakdown.values()))

    def test_missing_values_are_handled_safely(self) -> None:
        vector = FeatureVector(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            target_scope="GLOBAL",
            model_name="xgboost",
            features={"liquidity": None, "breadth": 0.2, "crypto": None},
            prediction_value=None,
            base_value=0.30,
        )
        explanation = ExplainabilityEngine().explain_from_shap_values(
            vector,
            shap_values={"liquidity": None, "breadth": 0.02, "crypto": 0.01},
        )

        self.assertTrue(explanation.additive_valid)
        self.assertAlmostEqual(explanation.prediction_value, 0.33)
        self.assertTrue(all(item.feature_value >= 0.0 or item.feature_name == "breadth" for item in explanation.driver_attributions))

    def test_persistence_adapter_uses_existing_exception_table(self) -> None:
        explanation = ExplainabilityEngine().explain_from_shap_values(
            feature_vector(prediction_value=0.62),
            base_value=0.40,
            shap_values={"liquidity": 0.12, "breadth": 0.08, "crypto": 0.02},
        )
        adapter = ExplainabilityPersistenceAdapter()
        row = adapter.to_row(explanation)

        self.assertEqual(adapter.table_name, "data_quality_exceptions")
        self.assertEqual(row["source_name"], "explainability_engine")
        payload = json.loads(row["bad_value_raw"])
        self.assertTrue(payload["additive_valid"])

    def test_persist_executes_insert(self) -> None:
        explanation = ExplainabilityEngine().explain_from_shap_values(
            feature_vector(prediction_value=0.62),
            base_value=0.40,
            shap_values={"liquidity": 0.12, "breadth": 0.08, "crypto": 0.02},
        )
        connection = FakeConnection()

        ExplainabilityPersistenceAdapter().persist(connection, explanation)

        sql, params = connection.cursor_obj.executed[0]
        self.assertIn("INSERT INTO data_quality_exceptions", sql)
        self.assertEqual(params[1], "explainability_engine")


def feature_vector(*, prediction_value: float | None, day: int = 0) -> FeatureVector:
    return FeatureVector(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day),
        target_scope="GLOBAL",
        model_name="xgboost",
        features={"liquidity": 60.0, "breadth": 0.2, "crypto": 55.0},
        prediction_value=prediction_value,
    )


class FakeShapProvider:
    def __init__(self, *, base_value: float, shap_values: list[float]) -> None:
        self.base_value = base_value
        self.shap_values = shap_values
        self.seen_background: list[list[float]] = []
        self.seen_feature_names: list[str] = []

    def explain(
        self,
        model: object,
        feature_names: list[str],
        feature_values: list[float],
        background: list[list[float]],
    ) -> tuple[float, list[float]]:
        self.seen_feature_names = list(feature_names)
        self.seen_background = list(background)
        return self.base_value, self.shap_values


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
