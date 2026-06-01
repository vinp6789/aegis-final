from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from analytics.synthesis.probability_aggregator import FORECAST_TYPES, HORIZONS, AggregatorInput
from analytics.synthesis.scenario_engine import (
    SCENARIO_NAMES,
    REGIME_STATES,
    ScenarioEngine,
    load_threshold_config,
    transition_row_from_systemic,
)


class Phase11ScenarioEngineTest(unittest.TestCase):
    def test_transition_tree_rows_sum_to_one(self) -> None:
        row = transition_row_from_systemic(0.72)

        self.assertEqual(set(row), set(REGIME_STATES))
        self.assertAlmostEqual(sum(row.values()), 1.0)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in row.values()))

    def test_scenario_run_generates_valid_probability_matrices(self) -> None:
        run = ScenarioEngine().run(base_input(), historical_inputs())

        self.assertEqual([scenario.scenario_name for scenario in run.scenarios], list(SCENARIO_NAMES))
        for scenario in run.scenarios:
            matrix = scenario.probability_matrix
            self.assertEqual(set(matrix.probabilities), set(FORECAST_TYPES))
            for forecast_type in FORECAST_TYPES:
                vector = matrix.vector(forecast_type)
                self.assertEqual(len(vector), len(HORIZONS))
                self.assertEqual(vector, sorted(vector))
                self.assertTrue(all(0.0 <= value <= 1.0 for value in vector))

    def test_scenario_novelty_score_is_normalized(self) -> None:
        engine = ScenarioEngine()

        base_novelty = engine.scenario_novelty_score(base_input(), historical_inputs())
        tail_novelty = engine.scenario_novelty_score(
            engine.apply_scenario_shock("TAIL_RISK", base_input()),
            historical_inputs(),
        )

        self.assertTrue(0.0 <= base_novelty <= 100.0)
        self.assertTrue(0.0 <= tail_novelty <= 100.0)
        self.assertGreaterEqual(tail_novelty, base_novelty)

    def test_counterfactual_optimizer_yields_five_distinct_paths(self) -> None:
        paths = ScenarioEngine().counterfactual_paths(base_input())

        self.assertEqual(len(paths), 5)
        self.assertEqual(len({path.action_name for path in paths}), 5)
        self.assertTrue(all(0.0 <= path.systemic_stress_12m <= 1.0 for path in paths))
        self.assertEqual(
            [path.risk_reduction for path in paths],
            sorted([path.risk_reduction for path in paths], reverse=True),
        )

    def test_optimizer_outputs_checked_in_full_run(self) -> None:
        run = ScenarioEngine().run(base_input(), historical_inputs())

        self.assertEqual(len(run.counterfactual_paths), 5)
        self.assertEqual(set(run.transition_matrix), set(REGIME_STATES))
        for row in run.transition_matrix.values():
            self.assertAlmostEqual(sum(row.values()), 1.0)

    def test_config_loads_threshold_bounds(self) -> None:
        config = load_threshold_config()

        self.assertEqual(config.mild_shock_std, 0.5)
        self.assertEqual(config.moderate_shock_std, 1.0)
        self.assertEqual(config.severe_shock_std, 2.0)
        self.assertEqual(config.extreme_shock_std, 3.0)
        self.assertEqual(config.counterfactual_top_k, 5)

    def test_missing_value_handling(self) -> None:
        run = ScenarioEngine().run(
            AggregatorInput(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            [],
        )

        self.assertEqual(len(run.scenarios), len(SCENARIO_NAMES))
        self.assertEqual(len(run.counterfactual_paths), 5)
        self.assertTrue(all(0.0 <= scenario.novelty_score <= 100.0 for scenario in run.scenarios))


def base_input() -> AggregatorInput:
    return AggregatorInput(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        liquidity_index=45.0,
        liquidity_transmission_score=42.0,
        leading_diffusion_index=-0.2,
        hhi_concentration_score=0.35,
        discovery_score=60.0,
        backtest_sharpe=0.8,
        backtest_win_rate=0.58,
        regime_probability=0.65,
        volatility_index=55.0,
        crypto_liquidity_index=40.0,
    )


def historical_inputs() -> list[AggregatorInput]:
    return [
        AggregatorInput(
            timestamp=datetime(2025, 12, 1, tzinfo=timezone.utc) + timedelta(days=index),
            liquidity_index=55.0 + index,
            liquidity_transmission_score=45.0 + index * 0.5,
            leading_diffusion_index=-0.1 + index * 0.01,
            hhi_concentration_score=0.30 + index * 0.005,
            discovery_score=55.0 + index,
            backtest_sharpe=0.5,
            backtest_win_rate=0.55,
            regime_probability=0.45 + index * 0.01,
            volatility_index=35.0 + index,
            crypto_liquidity_index=50.0 - index,
        )
        for index in range(10)
    ]


if __name__ == "__main__":
    unittest.main()
