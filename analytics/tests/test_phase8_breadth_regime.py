from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from analytics.diagnostics.breadth_engine import BreadthEngine, ComponentSnapshot
from analytics.diagnostics.macro_regime import MacroRegimeClassifier, RegimeInput, RegimeState


class Phase8BreadthRegimeTest(unittest.TestCase):
    def test_breadth_equation_validation(self) -> None:
        engine = BreadthEngine()
        metrics = engine.calculate_daily_metrics(
            [
                component("A", 110, 100, 100, 90, 400, new_high=True),
                component("B", 95, 100, 100, 100, 300, new_low=True),
                component("C", 105, 100, 99, 101, 200, new_high=True),
                component("D", 100, 100, 99, 101, 100),
            ]
        )

        self.assertEqual(metrics.advance_decline_ratio, 2.0)
        self.assertAlmostEqual(metrics.new_high_new_low_ratio, 2 / 3, places=5)
        self.assertEqual(metrics.percent_above_50_sma, 0.75)
        self.assertEqual(metrics.percent_above_200_sma, 0.5)
        self.assertTrue(-1.0 <= metrics.leading_diffusion_index <= 1.0)

    def test_hhi_validation_penalizes_concentration(self) -> None:
        engine = BreadthEngine()
        diversified = [
            component("A", 10, 9, 8, 7, 100),
            component("B", 10, 9, 8, 7, 100),
            component("C", 10, 9, 8, 7, 100),
            component("D", 10, 9, 8, 7, 100),
        ]
        concentrated = [
            component("A", 10, 9, 8, 7, 970),
            component("B", 10, 9, 8, 7, 10),
            component("C", 10, 9, 8, 7, 10),
            component("D", 10, 9, 8, 7, 10),
        ]

        diversified_metrics = engine.calculate_daily_metrics(diversified)
        concentrated_metrics = engine.calculate_daily_metrics(concentrated)

        self.assertAlmostEqual(diversified_metrics.hhi_concentration_score, 0.25)
        self.assertGreater(concentrated_metrics.hhi_concentration_score, 0.9)
        self.assertLess(
            concentrated_metrics.leading_diffusion_index,
            diversified_metrics.leading_diffusion_index,
        )

    def test_missing_values_are_handled_without_missing_outputs(self) -> None:
        metrics = BreadthEngine().calculate_daily_metrics(
            [
                component("A", None, 100, None, 100, None),
                component("B", 101, None, 100, None, 200),
                component("C", 98, 100, 99, 100, 300, new_low=True),
            ]
        )

        self.assertIsNotNone(metrics.leading_diffusion_index)
        self.assertIsNotNone(metrics.hhi_concentration_score)
        self.assertTrue(0.0 <= metrics.percent_above_50_sma <= 1.0)
        self.assertTrue(0.0 <= metrics.hhi_concentration_score <= 1.0)

    def test_regime_classification_validation(self) -> None:
        classifier = MacroRegimeClassifier()
        risk_on = classifier.classify(
            RegimeInput(
                timestamp=now(),
                liquidity_index=90.0,
                breadth=metrics(ldi=0.8, hhi=0.1),
                volatility_index=10.0,
            )
        )
        crisis = classifier.classify(
            RegimeInput(
                timestamp=now(),
                liquidity_index=5.0,
                breadth=metrics(ldi=-0.9, hhi=0.9),
                volatility_index=95.0,
            )
        )

        self.assertEqual(risk_on.regime_state, RegimeState.RISK_ON)
        self.assertEqual(crisis.regime_state, RegimeState.CRISIS)
        self.assertTrue(0.0 <= risk_on.regime_probability <= 1.0)
        self.assertTrue(0.0 <= crisis.regime_probability <= 1.0)

    def test_historical_component_simulation_daily_outputs(self) -> None:
        engine = BreadthEngine()
        history = []
        for day in range(5):
            history.append(
                [
                    component("A", 100 + day, 99 + day, 98 + day, 97 + day, 400, day=day),
                    component("B", 95 - day, 96 - day, 97, 98, 300, new_low=day == 4, day=day),
                    component("C", 100 + day * 0.5, 100, 99, 98, 200, day=day),
                ]
            )

        outputs = engine.calculate_history(history)

        self.assertEqual(len(outputs), 5)
        self.assertEqual([item.timestamp.date() for item in outputs], sorted(item.timestamp.date() for item in outputs))
        self.assertTrue(all(-1.0 <= item.leading_diffusion_index <= 1.0 for item in outputs))
        self.assertTrue(all(0.0 <= item.hhi_concentration_score <= 1.0 for item in outputs))

    def test_output_persistence_verification(self) -> None:
        breadth_engine = BreadthEngine()
        classifier = MacroRegimeClassifier()
        connection = FakeConnection()
        breadth = breadth_engine.calculate_daily_metrics(
            [component("A", 110, 100, 100, 90, 100), component("B", 90, 100, 95, 100, 100)]
        )
        classification = classifier.classify(
            RegimeInput(
                timestamp=breadth.timestamp,
                liquidity_index=55.0,
                breadth=breadth,
                volatility_index=30.0,
            )
        )

        breadth_engine.persist_metrics(connection, [breadth])
        classifier.persist_classifications(connection, [classification])

        self.assertEqual(len(connection.statements), 2)
        self.assertIn("INSERT INTO breadth_metrics", connection.statements[0][0])
        self.assertIn("INSERT INTO macro_regime_classifications", connection.statements[1][0])
        self.assertIn(classification.regime_state.value, connection.statements[1][1])


def now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def component(
    ticker: str,
    close: float | None,
    previous: float | None,
    sma50: float | None,
    sma200: float | None,
    cap: float | None,
    *,
    new_high: bool = False,
    new_low: bool = False,
    day: int = 0,
) -> ComponentSnapshot:
    return ComponentSnapshot(
        timestamp=now() + timedelta(days=day),
        ticker=ticker,
        close_price=close,
        previous_close=previous,
        sma_50=sma50,
        sma_200=sma200,
        market_cap=cap,
        new_high=new_high,
        new_low=new_low,
    )


def metrics(*, ldi: float, hhi: float) -> Any:
    return type(
        "Metrics",
        (),
        {
            "leading_diffusion_index": ldi,
            "hhi_concentration_score": hhi,
        },
    )()


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
