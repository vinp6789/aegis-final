from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol, Sequence

from ingestion.adapters.base_client import FetchResult, SourceHealthMetrics
from ingestion.data_quality.exception_logger import QualityException


PHASE1_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "daily_market_metrics": (
        "timestamp",
        "asset_id",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "market_cap",
    ),
    "macro_liquidity_indicators": (
        "timestamp",
        "indicator_code",
        "value",
        "revised",
        "release_date",
    ),
    "crypto_market_metrics_v2": (
        "timestamp",
        "ticker",
        "market_cap",
        "close_price",
        "volume_24h",
    ),
    "stablecoin_liquidity_growth": (
        "timestamp",
        "token_symbol",
        "circulating_supply",
        "daily_growth_pct",
        "weekly_growth_pct",
        "monthly_growth_pct",
    ),
    "india_liquidity_flows": (
        "timestamp",
        "rbi_total_assets",
        "net_laf_absorption",
        "marginal_standing_facility",
        "standing_deposit_facility",
        "bank_credit_growth_yoy",
        "bank_deposit_growth_yoy",
        "fii_net_flow_usd",
        "dii_net_flow_inr",
    ),
    "ingestion_source_health": (
        "timestamp",
        "source_name",
        "availability_rate",
        "freshness_seconds",
        "missing_value_ratio",
        "average_latency_ms",
        "validation_success_rate",
        "source_health_score",
    ),
    "data_quality_exceptions": (
        "timestamp",
        "source_name",
        "field_name",
        "exception_type",
        "bad_value_raw",
        "severity",
    ),
}


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


class Phase1Persistence:
    """DB-API persistence restricted to Phase 1 tables."""

    def persist_fetch_result(self, connection: DbConnection, result: FetchResult, target_table: str) -> None:
        self.insert_rows(connection, target_table, result.records)
        self.persist_health(connection, result.health)
        self.persist_exceptions(connection, result.exceptions)

    def persist_health(self, connection: DbConnection, health: SourceHealthMetrics) -> None:
        self.insert_rows(
            connection,
            "ingestion_source_health",
            [
                {
                    "timestamp": datetime.now(timezone.utc),
                    **asdict(health),
                }
            ],
        )

    def persist_exceptions(
        self,
        connection: DbConnection,
        exceptions: Iterable[QualityException],
    ) -> None:
        rows = [
            {
                "timestamp": exception.timestamp.astimezone(timezone.utc),
                "source_name": exception.source_name,
                "field_name": exception.field_name,
                "exception_type": exception.exception_type,
                "bad_value_raw": exception.bad_value_raw,
                "severity": exception.severity.value,
            }
            for exception in exceptions
        ]
        self.insert_rows(connection, "data_quality_exceptions", rows)

    def insert_rows(
        self,
        connection: DbConnection,
        table_name: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        if not rows:
            return
        if table_name not in PHASE1_TABLE_COLUMNS:
            raise ValueError(f"Refusing to persist non-Phase-1 table: {table_name}")
        columns = PHASE1_TABLE_COLUMNS[table_name]
        placeholders = ", ".join(["%s"] * len(columns))
        column_sql = ", ".join(columns)
        sql = f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})"
        with connection.cursor() as cursor:
            for row in rows:
                cursor.execute(sql, tuple(row.get(column) for column in columns))
