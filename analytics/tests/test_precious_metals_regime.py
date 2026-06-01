from __future__ import annotations

import unittest

from analytics.synthesis.precious_metals_regime import PreciousMetalsInput, PreciousMetalsRegimeEngine


class PreciousMetalsRegimeEngineTest(unittest.TestCase):
    def test_outputs_are_bounded_and_scores_sum_to_100(self) -> None:
        result = PreciousMetalsRegimeEngine().evaluate(
            PreciousMetalsInput(
                liquidity_index=80.0,
                credit_stress_index=35.0,
                market_crash_probability=0.35,
                systemic_stress_probability=0.40,
                inflation_pressure=70.0,
                real_rate_pressure=75.0,
                dollar_pressure=40.0,
                gold_silver_ratio=95.0,
            )
        )

        probabilities = [
            result.gold_bull_probability,
            result.gold_bear_probability,
            result.gold_acceleration_probability,
            result.gold_correction_probability,
            result.silver_bull_probability,
            result.silver_bear_probability,
            result.silver_acceleration_probability,
            result.silver_correction_probability,
        ]
        self.assertTrue(all(0.0 <= value <= 1.0 for value in probabilities))
        self.assertAlmostEqual(
            result.gold_buy_score + result.gold_hold_score + result.gold_sell_score,
            100.0,
            places=2,
        )
        self.assertAlmostEqual(
            result.silver_buy_score + result.silver_hold_score + result.silver_sell_score,
            100.0,
            places=2,
        )
        self.assertTrue(0.0 <= result.gold_relative_value_score <= 100.0)
        self.assertTrue(0.0 <= result.silver_relative_value_score <= 100.0)
        self.assertGreater(len(result.historical_precious_metal_analogs), 0)

    def test_high_gold_silver_ratio_favors_silver_relative_value(self) -> None:
        result = PreciousMetalsRegimeEngine().evaluate(PreciousMetalsInput(gold_silver_ratio=115.0))

        self.assertGreater(result.silver_relative_value_score, result.gold_relative_value_score)
        self.assertGreater(result.silver_buy_score, 0.0)

    def test_1970s_inflation_environment_matches_bull_analogs(self) -> None:
        result = PreciousMetalsRegimeEngine().evaluate(
            PreciousMetalsInput(
                liquidity_index=40.0,
                credit_stress_index=70.0,
                market_crash_probability=0.70,
                systemic_stress_probability=0.75,
                inflation_pressure=95.0,
                real_rate_pressure=90.0,
                dollar_pressure=50.0,
                gold_silver_ratio=55.0,
            )
        )

        regimes = {analog["regime"] for analog in result.to_dict()["historical_precious_metal_analogs"]}
        self.assertTrue({"BULL_RUN", "ACCUMULATION"} & regimes)


if __name__ == "__main__":
    unittest.main()
