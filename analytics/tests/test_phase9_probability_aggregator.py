from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from analytics.synthesis.probability_aggregator import (
    BreadthToProbabilityAdapter,
    DiscoveryToProbabilityAdapter,
    FORECAST_TYPES,
    HORIZONS,
    AggregatorInput,
    LiquidityToProbabilityAdapter,
    ProbabilityAggregator,
    ProbabilityMatrixPersistenceAdapter,
    WalkForwardToProbabilityAdapter,
    pava_increasing,
)


class Phase9ProbabilityAggregatorTest(unittest.TestCase):
    def test_probability_calculation_validation(self) -> None:
        matrix = ProbabilityAggregator().aggregate(sample_input())

        self.assertEqual(set(matrix.probabilities), set(FORECAST_TYPES))
        for forecast_type in FORECAST_TYPES:
            self.assertEqual(set(matrix.probabilities[forecast_type]), set(HORIZONS))
            self.assertTrue(all(0.0 <= value <= 1.0 for value in matrix.vector(forecast_type)))
        self.assertTrue(0.0 <= matrix.early_warning_score <= 100.0)
        self.assertTrue(0.0 <= matrix.confidence_score <= 100.0)

    def test_monotonicity_validation_across_all_horizons(self) -> None:
        matrix = ProbabilityAggregator().aggregate(sample_input(liquidity_index=15.0, leading_diffusion_index=-0.8))

        for forecast_type in FORECAST_TYPES:
            vector = matrix.vector(forecast_type)
            self.assertEqual(vector, sorted(vector))

    def test_pava_validation_corrects_non_monotonic_vector(self) -> None:
        corrected = pava_increasing([0.20, 0.40, 0.30, 0.70, 0.60])

        self.assertEqual(corrected, sorted(corrected))
        self.assertEqual(len(corrected), 5)
        self.assertAlmostEqual(corrected[1], 0.35)
        self.assertAlmostEqual(corrected[2], 0.35)

    def test_probability_calibration_inheritance_from_phase6_outputs(self) -> None:
        aggregator = ProbabilityAggregator(
            calibrators={"market_crash": StaticCalibrator([1.2, 0.9, 0.7, -0.1, 0.8])}
        )

        matrix = aggregator.aggregate(sample_input())
        vector = matrix.vector("market_crash")

        self.assertEqual(vector, sorted(vector))
        self.assertTrue(all(0.0 <= value <= 1.0 for value in vector))
        self.assertEqual(aggregator.calibrators["market_crash"].calls, 1)

    def test_historical_pipeline_execution(self) -> None:
        aggregator = ProbabilityAggregator()
        history = [
            sample_input(
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
                liquidity_index=70.0 - index,
                leading_diffusion_index=0.5 - index * 0.02,
                volatility_index=20.0 + index,
            )
            for index in range(10)
        ]

        matrices = aggregator.aggregate_history(history)

        self.assertEqual(len(matrices), 10)
        self.assertEqual([item.timestamp for item in matrices], sorted(item.timestamp for item in matrices))
        self.assertTrue(all(0.0 <= item.early_warning_score <= 100.0 for item in matrices))

    def test_extreme_probability_swing_validation(self) -> None:
        stable = ProbabilityAggregator().aggregate(
            sample_input(previous_systemic_stress_12m=0.55, liquidity_index=70.0, leading_diffusion_index=0.4)
        )
        swing = ProbabilityAggregator().aggregate(
            sample_input(previous_systemic_stress_12m=0.05, liquidity_index=5.0, leading_diffusion_index=-1.0, volatility_index=95.0)
        )

        self.assertFalse(stable.extreme_swing_detected)
        self.assertTrue(swing.extreme_swing_detected)
        self.assertGreater(swing.early_warning_score, stable.early_warning_score)

    def test_missing_value_handling(self) -> None:
        matrix = ProbabilityAggregator().aggregate(
            AggregatorInput(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        )

        for forecast_type in FORECAST_TYPES:
            self.assertTrue(all(0.0 <= value <= 1.0 for value in matrix.vector(forecast_type)))
        self.assertFalse(matrix.extreme_swing_detected)

    def test_typed_adapters_and_probability_matrix_persistence(self) -> None:
        payload = {}
        payload.update(DiscoveryToProbabilityAdapter().to_input(type("Discovery", (), {"current_score": 72.0})()))
        payload.update(
            LiquidityToProbabilityAdapter().to_input(
                type(
                    "Liquidity",
                    (),
                    {
                        "global_liquidity_index": 35.0,
                        "liquidity_transmission_score": 40.0,
                        "crypto_liquidity_index": 25.0,
                    },
                )()
            )
        )
        payload.update(
            BreadthToProbabilityAdapter().to_input(
                type("Breadth", (), {"leading_diffusion_index": -0.5, "hhi_concentration_score": 0.7})(),
                type("Regime", (), {"regime_probability": 0.85})(),
            )
        )
        payload.update(
            WalkForwardToProbabilityAdapter().to_input(
                type("Stats", (), {"sharpe": 0.2, "win_rate": 0.52})()
            )
        )
        matrix = ProbabilityAggregator().aggregate(
            AggregatorInput(
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                volatility_index=75.0,
                **payload,
            )
        )
        connection = FakeConnection()

        ProbabilityMatrixPersistenceAdapter().persist(connection, matrix)

        self.assertEqual(len(connection.statements), 1)
        sql, values = connection.statements[0]
        self.assertIn("INSERT INTO probability_matrix_outputs_v3", sql)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in values[2:12]))
        self.assertIn(values[-1], {"LOW_RISK", "WATCH", "ELEVATED", "HIGH_RISK", "CRISIS"})


def sample_input(
    *,
    timestamp: datetime | None = None,
    liquidity_index: float | None = 45.0,
    leading_diffusion_index: float | None = -0.2,
    volatility_index: float | None = 55.0,
    previous_systemic_stress_12m: float | None = None,
) -> AggregatorInput:
    return AggregatorInput(
        timestamp=timestamp or datetime(2026, 1, 1, tzinfo=timezone.utc),
        liquidity_index=liquidity_index,
        liquidity_transmission_score=42.0,
        leading_diffusion_index=leading_diffusion_index,
        hhi_concentration_score=0.35,
        discovery_score=60.0,
        backtest_sharpe=0.8,
        backtest_win_rate=0.58,
        regime_probability=0.65,
        volatility_index=volatility_index,
        crypto_liquidity_index=40.0,
        previous_systemic_stress_12m=previous_systemic_stress_12m,
    )


class StaticCalibrator:
    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.calls = 0

    def predict(self, probabilities: list[float]) -> list[float]:
        self.calls += 1
        return self.values


class FakeCursor:
    def __init__(self, statements: list[tuple[str, tuple[object, ...]]]) -> None:
        self.statements = statements

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, values: tuple[object, ...]) -> None:
        self.statements.append((sql, values))


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[object, ...]]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.statements)


if __name__ == "__main__":
    unittest.main()
