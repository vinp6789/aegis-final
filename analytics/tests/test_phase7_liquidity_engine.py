from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from analytics.diagnostics.liquidity_engine import (
    LiquidityEngine,
    LiquidityInput,
    normalize_series,
    transmission_scores,
)


class Phase7LiquidityEngineTest(unittest.TestCase):
    def test_synthetic_formula_validation(self) -> None:
        engine = LiquidityEngine()

        us_raw = engine.us_liquidity_raw(
            {
                "fed_balance_sheet": 8000.0,
                "bank_reserves": 3000.0,
                "tga": 700.0,
                "reverse_repo": 900.0,
            }
        )
        india_raw = engine.india_liquidity_raw(
            {
                "rbi_liquidity": 100.0,
                "laf": 20.0,
                "msf": 5.0,
                "sdf": 10.0,
                "fii_flows": 3.0,
                "dii_flows": 4.0,
            }
        )
        crypto_raw = engine.crypto_liquidity_raw(
            {
                "stablecoin_supply_growth": 5.0,
                "usdt_growth": 2.0,
                "usdc_growth": 1.0,
                "coinbase_premium": 0.5,
                "btc_spot_cvd": 8.0,
            }
        )

        self.assertEqual(us_raw, 9400.0)
        self.assertEqual(india_raw, 142.0)
        self.assertEqual(crypto_raw, 16.5)
        self.assertAlmostEqual(
            engine.global_liquidity_raw(
                us_raw=us_raw,
                india_raw=india_raw,
                macro_values={
                    "global_macro_liquidity": 500.0,
                    "global_credit_growth": 20.0,
                    "dollar_liquidity": 30.0,
                },
            ),
            4368.0,
        )

    def test_normalization_bounds_inputs_to_0_100(self) -> None:
        self.assertEqual(normalize_series([10.0, 20.0, 30.0]), [0.0, 50.0, 100.0])
        self.assertEqual(normalize_series([5.0, 5.0, 5.0]), [50.0, 50.0, 50.0])

    def test_missing_value_handling_and_daily_outputs(self) -> None:
        engine = LiquidityEngine()
        snapshots = engine.build_daily_indices(
            us_inputs=[
                row(0, {"fed_balance_sheet": 100.0, "tga": None, "reverse_repo": 10.0}),
                row(1, {"fed_balance_sheet": 110.0, "tga": 4.0, "reverse_repo": None}),
            ],
            india_inputs=[row(0, {"rbi_liquidity": None}), row(1, {"rbi_liquidity": 10.0})],
            crypto_inputs=[row(0, {"stablecoin_supply_growth": 1.0}), row(1, {"usdt_growth": None})],
            macro_inputs=[row(0, {"global_macro_liquidity": 5.0}), row(1, {"global_macro_liquidity": None})],
            transmission_window=2,
        )

        self.assertEqual(len(snapshots), 2)
        self.assertTrue(engine.verify_indices(snapshots))
        self.assertEqual(
            [snapshot.timestamp for snapshot in snapshots],
            [
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 2, tzinfo=timezone.utc),
            ],
        )

    def test_liquidity_transmission_score_tracks_correlation(self) -> None:
        scores = transmission_scores(
            [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            window=3,
        )

        self.assertEqual(scores[:3], [50.0, 50.0, 50.0])
        self.assertEqual(scores[-1], 50.0)

        varied = transmission_scores(
            [10.0, 20.0, 25.0, 35.0, 55.0, 60.0],
            [5.0, 7.0, 8.0, 11.0, 18.0, 20.0],
            window=3,
        )
        self.assertGreater(varied[-1], 90.0)

    def test_feast_integration_uses_fred_and_rbi_datasets(self) -> None:
        engine = LiquidityEngine()
        store = FakeOfflineStore()

        result = engine.fetch_feast_liquidity_features(
            store,
            entity_df=[{"indicator_code": "FED_BALANCE_SHEET"}],
        )

        self.assertEqual(result, {"rows": 1})
        self.assertEqual(store.calls, 1)
        requested = store.requested_features
        self.assertTrue(any("fed_balance_sheet" in feature for feature in requested))
        self.assertTrue(any("tga" in feature for feature in requested))
        self.assertTrue(any("reverse_repo" in feature for feature in requested))
        self.assertTrue(any("rbi_liquidity" in feature for feature in requested))
        self.assertTrue(any("laf" in feature for feature in requested))

    def test_index_verification_rejects_empty_or_out_of_bounds(self) -> None:
        engine = LiquidityEngine()

        self.assertFalse(engine.verify_indices([]))
        snapshots = engine.build_daily_indices(
            us_inputs=[row(index, {"fed_balance_sheet": 100.0 + index, "tga": 1.0, "reverse_repo": 1.0}) for index in range(8)],
            india_inputs=[row(index, {"rbi_liquidity": 10.0 + index, "laf": index}) for index in range(8)],
            crypto_inputs=[row(index, {"stablecoin_supply_growth": index}) for index in range(8)],
            macro_inputs=[row(index, {"global_macro_liquidity": 50.0 + index}) for index in range(8)],
            transmission_window=3,
        )

        self.assertTrue(engine.verify_indices(snapshots))


def row(offset: int, values: dict[str, float | int | None]) -> LiquidityInput:
    return LiquidityInput(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset),
        values=values,
    )


class FakeOfflineStore:
    def __init__(self) -> None:
        self.calls = 0
        self.requested_features: list[str] = []

    def get_historical_features(self, *, features: list[str], entity_df: Any) -> dict[str, int]:
        self.calls += 1
        self.requested_features = list(features)
        return {"rows": len(entity_df)}


if __name__ == "__main__":
    unittest.main()
