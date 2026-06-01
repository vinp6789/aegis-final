from __future__ import annotations

import unittest

from analytics.synthesis.valuation_layer import ValuationEngine, ValuationInput


class ValuationLayerTest(unittest.TestCase):
    def test_high_valuation_environment_has_high_risk(self) -> None:
        result = ValuationEngine().evaluate(
            ValuationInput(cape=38.0, earnings_yield=2.2, dividend_yield=1.2, market_cap_to_gdp=190.0)
        )

        self.assertGreater(result.valuation_risk_score, 75.0)
        self.assertLess(result.valuation_score, 25.0)
        self.assertTrue(0.0 <= result.valuation_percentile <= 100.0)

    def test_low_valuation_environment_has_high_score(self) -> None:
        result = ValuationEngine().evaluate(
            ValuationInput(cape=11.0, earnings_yield=7.0, dividend_yield=4.0, market_cap_to_gdp=60.0)
        )

        self.assertGreater(result.valuation_score, result.valuation_risk_score)

    def test_missing_inputs_return_neutral_bootstrap(self) -> None:
        result = ValuationEngine().evaluate(ValuationInput())

        self.assertEqual(result.valuation_score, 50.0)
        self.assertEqual(result.valuation_risk_score, 50.0)


if __name__ == "__main__":
    unittest.main()
