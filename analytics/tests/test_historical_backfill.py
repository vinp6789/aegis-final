from __future__ import annotations

import unittest
from datetime import datetime, timezone

from analytics.research.historical_backfill import (
    HistoricalBackfillPipeline,
    HistoricalReplayEngine,
    HistoricalPoint,
    MARKET_EVENT_CATALOG,
    ReconstructedForecast,
    build_coverage_report,
    build_research_report,
    build_validation_dataset,
    coverage_summary,
    coverage_report_from_points,
    historical_replay_validation_statistics,
    point_in_time_feature_row,
    research_report_to_dict,
)
from analytics.validation.model_validation import SYSTEMIC_STRESS_RETURN_THRESHOLD


class HistoricalBackfillTest(unittest.TestCase):
    def test_coverage_report_contains_required_categories(self) -> None:
        report = build_coverage_report(current_year=2026)
        categories = {row["category"] for row in report}

        for category in {
            "equity indices",
            "gold",
            "silver",
            "dollar index",
            "liquidity",
            "credit",
            "inflation",
            "interest rates",
            "yield curves",
            "valuation",
        }:
            self.assertIn(category, categories)

    def test_event_catalog_contains_required_crises(self) -> None:
        ids = {event.event_id for event in MARKET_EVENT_CATALOG}

        for event_id in {"1907", "1929", "1973", "1987", "1998", "2000", "2008", "2011", "2020", "2022"}:
            self.assertIn(event_id, ids)

    def test_reconstructed_forecasts_are_marked_as_point_in_time_replay(self) -> None:
        pipeline = HistoricalBackfillPipeline()
        points_by_code = sample_points()

        forecasts = pipeline.reconstruct_monthly_forecasts(points_by_code)

        self.assertTrue(forecasts)
        forecast_types = {forecast.forecast_type for forecast in forecasts}
        self.assertIn("panic_probability_12m", forecast_types)
        self.assertIn("expected_drawdown_12m", forecast_types)
        for forecast in forecasts:
            self.assertEqual(forecast.metadata["source"], "historical_replay")
            self.assertEqual(forecast.metadata["forecast_origin"], "historical_replay")
            self.assertTrue(forecast.metadata["replay_generated"])
            self.assertTrue(forecast.metadata["no_lookahead"])

    def test_point_in_time_features_do_not_use_future_values(self) -> None:
        points = sample_points()
        future = datetime(2008, 2, 1, tzinfo=timezone.utc)
        points["SHILLER_CAPE"].append(HistoricalPoint(future, "SHILLER_CAPE", 99.0, "future"))

        row = point_in_time_feature_row(points, datetime(2007, 1, 1, tzinfo=timezone.utc))

        self.assertEqual(row["SHILLER_CAPE"], 28.0)

    def test_replay_generates_production_shaped_outputs_and_resume_skips(self) -> None:
        pipeline = HistoricalBackfillPipeline()
        points = validation_points()

        run = pipeline.replay_history(
            points,
            start=datetime(2007, 1, 1, tzinfo=timezone.utc),
            end=datetime(2007, 3, 1, tzinfo=timezone.utc),
            completed_months=[datetime(2007, 2, 1, tzinfo=timezone.utc)],
        )

        self.assertEqual(run.summary.completed_months, 2)
        self.assertEqual(len(run.summary.skipped_months), 1)
        self.assertEqual(run.summary.skipped_months[0].reason, "already completed")
        output = run.predictions[0].outputs
        for key in (
            "market_crash_12m",
            "systemic_stress_12m",
            "buy_score",
            "hold_score",
            "sell_score",
            "expected_return_12m",
            "expected_drawdown_12m",
            "regime_state",
            "confidence",
            "credit_stress_index",
            "valuation_score",
            "gold_bull_probability",
            "silver_bear_probability",
        ):
            self.assertIn(key, output)

    def test_replay_validation_statistics_include_requested_metrics(self) -> None:
        run = HistoricalReplayEngine().run(validation_points())

        metrics = historical_replay_validation_statistics(run.validation_rows)

        for key in (
            "brier_score",
            "precision",
            "recall",
            "roc_auc",
            "calibration_error",
            "f1_score",
            "prediction_lead_time",
            "false_positive_rate",
            "false_negative_rate",
            "maximum_drawdown_avoided",
            "annualized_return",
            "sharpe_ratio",
            "sortino_ratio",
            "confusion_matrix",
            "calibration_curve",
            "model_reliability_trend",
        ):
            self.assertIn(key, metrics)

    def test_validation_uses_production_systemic_stress_threshold(self) -> None:
        start = datetime(2008, 1, 1, tzinfo=timezone.utc)
        points = {
            "SP500": [
                HistoricalPoint(start, "SP500", 100.0, "test"),
                HistoricalPoint(datetime(2009, 1, 1, tzinfo=timezone.utc), "SP500", 90.0, "test"),
            ]
        }
        forecasts = [
            ReconstructedForecast(start, "panic_probability_12m", 0.60, 70.0, {"source": "test"}),
        ]

        rows = build_validation_dataset(points, forecasts)

        self.assertEqual(SYSTEMIC_STRESS_RETURN_THRESHOLD, -0.08)
        self.assertEqual(rows[0].realized_outcome, 1)

    def test_persist_writes_only_existing_tables(self) -> None:
        pipeline = HistoricalBackfillPipeline()
        connection = FakeConnection()
        points_by_code = sample_points()
        forecasts = pipeline.reconstruct_monthly_forecasts(points_by_code)

        counts = pipeline.persist(connection, points_by_code, forecasts)

        self.assertGreater(counts["asset_registry"], 0)
        self.assertGreater(counts["daily_market_metrics"], 0)
        self.assertGreater(counts["macro_liquidity_indicators"], 0)
        self.assertGreater(counts["forecast_history"], 0)
        self.assertGreater(counts["crisis_replay_library"], 0)
        sql = "\n".join(connection.cursor_obj.executed_sql)
        for table_name in (
            "asset_registry",
            "daily_market_metrics",
            "macro_liquidity_indicators",
            "stablecoin_liquidity_growth",
            "forecast_history",
            "crisis_replay_library",
        ):
            self.assertIn(table_name, sql)
        self.assertNotIn("CREATE TABLE", sql.upper())

    def test_coverage_summary_reports_date_ranges(self) -> None:
        summary = coverage_summary(sample_points())

        self.assertEqual(summary["SP500"]["rows"], 14)
        self.assertEqual(summary["SP500"]["start"], "2007-01-01")
        self.assertEqual(summary["SP500"]["end"], "2008-02-01")

    def test_coverage_report_from_points_identifies_actual_gaps(self) -> None:
        report = coverage_report_from_points(
            HistoricalBackfillPipeline().specs,
            sample_points(),
            current_year=2008,
        )
        by_code = {row["target_code"]: row for row in report}

        self.assertEqual(by_code["SP500"]["observed_start_year"], 2007)
        self.assertEqual(by_code["SP500"]["observed_end_year"], 2008)
        self.assertGreater(by_code["SP500"]["missing_data_percentage"], 90.0)
        self.assertEqual(by_code["DJIA"]["coverage_status"], "MISSING")

    def test_validation_dataset_stores_inputs_predictions_outcomes_and_error(self) -> None:
        pipeline = HistoricalBackfillPipeline()
        points_by_code = validation_points()
        forecasts = pipeline.reconstruct_monthly_forecasts(points_by_code)

        rows = build_validation_dataset(points_by_code, forecasts)

        self.assertTrue(rows)
        first = rows[0]
        self.assertIn("panic_probability", first.inputs)
        self.assertIn("panic_probability_12m", first.predictions)
        self.assertIn(first.realized_outcome, {0, 1})
        self.assertTrue(0.0 <= first.prediction_error <= 1.0)
        self.assertGreaterEqual(first.lead_time_months, 0.0)

    def test_research_report_contains_required_readiness_fields(self) -> None:
        pipeline = HistoricalBackfillPipeline()
        points_by_code = validation_points()
        forecasts = pipeline.reconstruct_monthly_forecasts(points_by_code)
        validation_rows = pipeline.build_validation_dataset(points_by_code, forecasts)

        report = build_research_report(
            pipeline.specs,
            pipeline.events,
            points_by_code,
            validation_rows,
            as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        payload = research_report_to_dict(report)

        for key in (
            "coverage_by_dataset",
            "missing_data_percentage",
            "backfill_completeness",
            "historical_event_coverage",
            "validation_readiness",
            "forecast_maturity_estimate",
            "research_completeness_estimate",
            "remaining_historical_gaps",
        ):
            self.assertIn(key, payload)
        self.assertIn("append", payload["self_learning_process"])
        self.assertTrue(0.0 <= report.research_completeness_estimate <= 100.0)

    def test_persist_includes_validation_rows_and_research_report(self) -> None:
        pipeline = HistoricalBackfillPipeline()
        connection = FakeConnection()
        points_by_code = validation_points()
        forecasts = pipeline.reconstruct_monthly_forecasts(points_by_code)
        validation_rows = pipeline.build_validation_dataset(points_by_code, forecasts)
        report = pipeline.research_report(
            points_by_code,
            validation_rows,
            as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        counts = pipeline.persist(connection, points_by_code, forecasts, validation_rows, report)

        self.assertGreater(counts["historical_validation_rows"], 0)
        self.assertEqual(counts["research_report"], 1)
        sql = "\n".join(connection.cursor_obj.executed_sql)
        self.assertIn("forecast_history", sql)
        self.assertIn("data_quality_exceptions", sql)

    def test_persist_replay_run_uses_forecast_history_with_replay_metadata(self) -> None:
        pipeline = HistoricalBackfillPipeline()
        connection = FakeConnection()
        run = pipeline.replay_history(validation_points())

        counts = pipeline.persist_replay_run(connection, run)

        self.assertGreater(counts["forecast_history"], 0)
        self.assertGreater(counts["historical_validation_rows"], 0)
        self.assertEqual(counts["research_report"], 0)
        sql = "\n".join(connection.cursor_obj.executed_sql)
        self.assertIn("forecast_history", sql)
        self.assertNotIn("CREATE TABLE", sql.upper())
        forecast_payloads = connection.cursor_obj.executed_params[0]
        first_metadata = forecast_payloads[0][5]
        self.assertIn('"source": "historical_replay"', first_metadata)
        self.assertIn('"forecast_origin": "historical_replay"', first_metadata)
        self.assertIn('"replay_generated": true', first_metadata)
        self.assertIn('"no_lookahead": true', first_metadata)

    def test_completed_replay_months_reads_existing_forecast_history_rows(self) -> None:
        replay_date = datetime(2007, 1, 15, tzinfo=timezone.utc)
        connection = FakeConnection(fetch_rows=[(replay_date,)])

        completed = HistoricalBackfillPipeline().completed_replay_months(connection)

        self.assertEqual(completed, {datetime(2007, 1, 1, tzinfo=timezone.utc)})
        sql = "\n".join(connection.cursor_obj.executed_sql)
        self.assertIn("forecast_history", sql)
        self.assertIn("metadata->>'source' = 'historical_replay'", sql)
        self.assertEqual(connection.cursor_obj.executed_params[0], ("GLOBAL",))


def sample_points() -> dict[str, list[HistoricalPoint]]:
    timestamps = [datetime(2007, month, 1, tzinfo=timezone.utc) for month in range(1, 13)]
    timestamps += [datetime(2008, 1, 1, tzinfo=timezone.utc), datetime(2008, 2, 1, tzinfo=timezone.utc)]
    sp500 = [
        HistoricalPoint(timestamp, "SP500", 1400.0 - index * 20.0, "test")
        for index, timestamp in enumerate(timestamps)
    ]
    return {
        "SP500": sp500,
        "SHILLER_CAPE": [HistoricalPoint(timestamp, "SHILLER_CAPE", 28.0, "test") for timestamp in timestamps],
        "FRED_BAA": [HistoricalPoint(timestamp, "FRED_BAA", 7.0, "test") for timestamp in timestamps],
        "FRED_AAA": [HistoricalPoint(timestamp, "FRED_AAA", 5.5, "test") for timestamp in timestamps],
        "FRED_CPIAUCSL": [HistoricalPoint(timestamp, "FRED_CPIAUCSL", 210.0, "test") for timestamp in timestamps],
        "FRED_T10Y2Y": [HistoricalPoint(timestamp, "FRED_T10Y2Y", -0.2, "test") for timestamp in timestamps],
        "GOLD": [HistoricalPoint(timestamp, "GOLD", 700.0 + index * 10.0, "test") for index, timestamp in enumerate(timestamps)],
        "SILVER": [HistoricalPoint(timestamp, "SILVER", 12.0 + index * 0.2, "test") for index, timestamp in enumerate(timestamps)],
        "STABLECOIN_TOTAL": [HistoricalPoint(timestamp, "STABLECOIN_TOTAL", 1000.0 + index * 10.0, "test") for index, timestamp in enumerate(timestamps)],
    }


def validation_points() -> dict[str, list[HistoricalPoint]]:
    points = sample_points()
    extra_timestamps = [datetime(2008, month, 1, tzinfo=timezone.utc) for month in range(3, 13)]
    extra_timestamps += [datetime(2009, month, 1, tzinfo=timezone.utc) for month in range(1, 13)]
    points["SP500"].extend(
        [
            HistoricalPoint(timestamp, "SP500", 1120.0 - index * 18.0, "test")
            for index, timestamp in enumerate(extra_timestamps)
        ]
    )
    for code in ("SHILLER_CAPE", "FRED_BAA", "FRED_AAA", "FRED_CPIAUCSL", "FRED_T10Y2Y", "GOLD", "SILVER"):
        base = points[code][-1].value
        points[code].extend(
            [
                HistoricalPoint(timestamp, code, base, "test")
                for timestamp in extra_timestamps
            ]
        )
    return points


class FakeConnection:
    def __init__(self, fetch_rows: list[tuple[object, ...]] | None = None) -> None:
        self.cursor_obj = FakeCursor(fetch_rows or [])

    def cursor(self) -> "FakeCursor":
        return self.cursor_obj


class FakeCursor:
    def __init__(self, fetch_rows: list[tuple[object, ...]]) -> None:
        self.executed_sql: list[str] = []
        self.executed_params: list[object] = []
        self.fetch_rows = fetch_rows

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, _params: object = None) -> None:
        self.executed_sql.append(sql)
        self.executed_params.append(_params)

    def executemany(self, sql: str, _params: object = None) -> None:
        self.executed_sql.append(sql)
        self.executed_params.append(_params)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.fetch_rows


if __name__ == "__main__":
    unittest.main()
