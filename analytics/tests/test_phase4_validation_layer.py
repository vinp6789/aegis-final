from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from typing import Any

from analytics.validation.exception_logger import (
    FailureAction,
    StructuredValidationExceptionLogger,
    ValidationSeverity,
)
from analytics.validation.freshness_validator import (
    FRESHNESS_VALIDATION_RULES,
    FreshnessValidator,
)
from analytics.validation.outlier_detector import OUTLIER_DETECTION_RULES, OutlierDetector
from analytics.validation.quality_scoring import QUALITY_SCORING_RULES, QualityScorer
from analytics.validation.schema_validator import (
    SCHEMA_VALIDATION_RULES,
    FieldType,
    SchemaField,
    SchemaValidator,
)


class Phase4ValidationLayerTest(unittest.TestCase):
    def test_validation_rules_are_explicit_artifacts(self) -> None:
        rules = (
            *SCHEMA_VALIDATION_RULES,
            *OUTLIER_DETECTION_RULES,
            *FRESHNESS_VALIDATION_RULES,
            *QUALITY_SCORING_RULES,
        )

        self.assertGreaterEqual(len(rules), 8)
        for rule in rules:
            with self.subTest(rule=rule.rule_name):
                self.assertTrue(rule.rule_name)
                self.assertTrue(rule.description)
                self.assertTrue(rule.threshold)
                self.assertIn(rule.severity, set(ValidationSeverity))
                self.assertIn(rule.failure_action, set(FailureAction))

    def test_schema_validator_flags_failures_without_dropping_records(self) -> None:
        logger = StructuredValidationExceptionLogger()
        validator = SchemaValidator(logger=logger)
        records = [
            {"timestamp": "2026-05-27T00:00:00+00:00", "asset_id": "BTC", "close_price": 100.0},
            {"timestamp": "2026-05-27T00:00:00+00:00", "asset_id": "", "close_price": 100.0},
            {"timestamp": "bad-date", "asset_id": "ETH", "close_price": "bad-price"},
            {"timestamp": "2026-05-27T00:00:00+00:00", "asset_id": "SOL", "close_price": -1.0},
        ]

        result = validator.validate(
            source_name="unit_source",
            records=records,
            schema=[
                SchemaField("timestamp", FieldType.TIMESTAMP),
                SchemaField("asset_id", FieldType.STRING),
                SchemaField("close_price", FieldType.FLOAT, min_value=0.000001),
            ],
        )

        self.assertEqual(result.records, records)
        self.assertEqual(result.blocked_record_indexes, [1, 2, 3])
        self.assertEqual(result.valid_record_indexes, [0])
        self.assertEqual(len(logger.records), len(result.failures))
        self.assertIn("SCHEMA_REQUIRED_FIELD", {failure.rule.rule_name for failure in result.failures})
        self.assertIn("SCHEMA_FIELD_TYPE", {failure.rule.rule_name for failure in result.failures})
        self.assertIn("SCHEMA_NUMERIC_BOUNDS", {failure.rule.rule_name for failure in result.failures})

    def test_outlier_and_freshness_validators_flag_without_dropping_records(self) -> None:
        logger = StructuredValidationExceptionLogger()
        records = [
            {"timestamp": "2026-05-27T00:00:00+00:00", "close_price": 100.0},
            {"timestamp": "2026-05-27T00:00:00+00:00", "close_price": 101.0},
            {"timestamp": "2026-05-27T00:00:00+00:00", "close_price": 99.0},
            {"timestamp": "2026-05-20T00:00:00+00:00", "close_price": 10000.0},
        ]

        outlier_result = OutlierDetector(zscore_threshold=1.5, logger=logger).detect(
            source_name="unit_source",
            records=records,
            numeric_fields=["close_price"],
        )
        freshness_result = FreshnessValidator(max_age_seconds=86_400, logger=logger).validate(
            source_name="unit_source",
            records=records,
            timestamp_field="timestamp",
            as_of=datetime(2026, 5, 27, tzinfo=timezone.utc),
        )

        self.assertEqual(outlier_result.records, records)
        self.assertEqual(freshness_result.records, records)
        self.assertEqual(outlier_result.flagged_record_indexes, [3])
        self.assertEqual(freshness_result.stale_record_indexes, [3])
        self.assertIn("OUTLIER_ZSCORE", {failure.rule.rule_name for failure in logger.records})
        self.assertIn("FRESHNESS_MAX_AGE", {failure.rule.rule_name for failure in logger.records})

    def test_quality_scoring_generates_batch_failures(self) -> None:
        logger = StructuredValidationExceptionLogger()
        schema_result = SchemaValidator(logger=logger).validate(
            source_name="unit_source",
            records=[{"timestamp": "bad-date"}, {"timestamp": "2026-05-27T00:00:00+00:00"}],
            schema=[SchemaField("timestamp", FieldType.TIMESTAMP)],
        )

        score = QualityScorer(
            minimum_quality_score=80.0,
            max_critical_failure_ratio=0.0,
            logger=logger,
        ).score(
            source_name="unit_source",
            total_records=2,
            validation_failures=schema_result.failures,
        )

        self.assertLess(score.score, 80.0)
        self.assertTrue(score.blocked)
        self.assertIn("QUALITY_CRITICAL_FAILURE_RATIO", {failure.rule.rule_name for failure in score.failures})
        self.assertIn("QUALITY_SCORE_MINIMUM", {failure.rule.rule_name for failure in score.failures})

    def test_structured_logger_writes_all_failures_to_data_quality_exceptions(self) -> None:
        logger = StructuredValidationExceptionLogger()
        schema_result = SchemaValidator(logger=logger).validate(
            source_name="unit_source",
            records=[{"asset_id": ""}],
            schema=[SchemaField("asset_id", FieldType.STRING)],
        )
        connection = FakeConnection()

        logger.persist_failures(connection, schema_result.failures)

        self.assertEqual(len(connection.statements), len(schema_result.failures))
        sql, values = connection.statements[0]
        self.assertIn("INSERT INTO data_quality_exceptions", sql)
        self.assertEqual(values[1], "unit_source")
        self.assertEqual(values[2], "asset_id")
        self.assertEqual(values[3], "SCHEMA_REQUIRED_FIELD")
        self.assertEqual(values[5], "CRITICAL")
        payload = json.loads(values[4])
        self.assertEqual(payload["severity"], "CRITICAL")
        self.assertEqual(payload["failure_action"], "FLAG_RECORD")


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
