from datetime import timedelta

from feast import Entity, FeatureService, FeatureView, Field
from feast.infra.offline_stores.contrib.postgres_offline_store.postgres_source import (
    PostgreSQLSource,
)
from feast.types import Float64, UnixTimestamp


asset = Entity(
    name="asset",
    join_keys=["asset_id"],
    description="Asset identifier from asset_registry.asset_id.",
)

indicator = Entity(
    name="indicator",
    join_keys=["indicator_code"],
    description="Macro or liquidity indicator code.",
)


daily_market_metrics_source = PostgreSQLSource(
    name="daily_market_metrics_source",
    query="""
        SELECT
            timestamp,
            asset_id,
            open_price AS open,
            high_price AS high,
            low_price AS low,
            close_price AS close,
            volume,
            market_cap
        FROM daily_market_metrics
    """,
    timestamp_field="timestamp",
    description="Daily price, volume, and market-cap metrics from TimescaleDB.",
)

macro_liquidity_indicators_source = PostgreSQLSource(
    name="macro_liquidity_indicators_source",
    table="macro_liquidity_indicators",
    timestamp_field="timestamp",
    description="Macroeconomic and liquidity indicators from TimescaleDB.",
)

crypto_onchain_metrics_source = PostgreSQLSource(
    name="crypto_onchain_metrics_source",
    table="crypto_onchain_metrics",
    timestamp_field="timestamp",
    description="Crypto on-chain metrics from TimescaleDB.",
)

liquidity_diagnostics_source = PostgreSQLSource(
    name="liquidity_diagnostics_source",
    query="""
        WITH macro AS (
            SELECT
                timestamp,
                MAX(CASE WHEN indicator_code = 'FED_BALANCE_SHEET' THEN value END) AS fed_balance_sheet,
                MAX(CASE WHEN indicator_code = 'TGA' THEN value END) AS tga,
                MAX(CASE WHEN indicator_code = 'REVERSE_REPO' THEN value END) AS reverse_repo
            FROM macro_liquidity_indicators
            GROUP BY timestamp
        )
        SELECT
            COALESCE(macro.timestamp, india.timestamp) AS timestamp,
            'GLOBAL_LIQUIDITY' AS indicator_code,
            macro.fed_balance_sheet,
            macro.tga,
            macro.reverse_repo,
            india.rbi_total_assets AS rbi_liquidity,
            india.net_laf_absorption AS laf,
            india.marginal_standing_facility AS msf,
            india.standing_deposit_facility AS sdf,
            india.fii_net_flow_usd AS fii_flows,
            india.dii_net_flow_inr AS dii_flows
        FROM macro
        FULL OUTER JOIN india_liquidity_flows india
            ON macro.timestamp = india.timestamp
    """,
    timestamp_field="timestamp",
    description="Wide liquidity diagnostics view for Phase 7 stabilization interfaces.",
)


daily_market_metrics = FeatureView(
    name="daily_market_metrics",
    entities=[asset],
    ttl=timedelta(days=730),
    schema=[
        Field(name="open", dtype=Float64),
        Field(name="high", dtype=Float64),
        Field(name="low", dtype=Float64),
        Field(name="close", dtype=Float64),
        Field(name="volume", dtype=Float64),
        Field(name="market_cap", dtype=Float64),
    ],
    source=daily_market_metrics_source,
    online=True,
    description="Daily market metrics mapped from the Phase 1 TimescaleDB schema.",
    tags={"phase": "2", "source_table": "daily_market_metrics", "version": "v1"},
)

macro_liquidity_indicators = FeatureView(
    name="macro_liquidity_indicators",
    entities=[indicator],
    ttl=timedelta(days=3650),
    schema=[
        Field(name="value", dtype=Float64),
        Field(name="release_date", dtype=UnixTimestamp),
    ],
    source=macro_liquidity_indicators_source,
    online=True,
    description="Macro and liquidity indicator values mapped by indicator code.",
    tags={"phase": "2", "source_table": "macro_liquidity_indicators", "version": "v1"},
)

crypto_onchain_metrics = FeatureView(
    name="crypto_onchain_metrics",
    entities=[asset],
    ttl=timedelta(days=730),
    schema=[
        Field(name="mvrv_z_score", dtype=Float64),
        Field(name="ssr_ratio", dtype=Float64),
        Field(name="stablecoin_inflow_volume", dtype=Float64),
    ],
    source=crypto_onchain_metrics_source,
    online=True,
    description="Crypto on-chain features mapped from the Phase 1 TimescaleDB schema.",
    tags={"phase": "2", "source_table": "crypto_onchain_metrics", "version": "v1"},
)

liquidity_diagnostics = FeatureView(
    name="liquidity_diagnostics",
    entities=[indicator],
    ttl=timedelta(days=3650),
    schema=[
        Field(name="fed_balance_sheet", dtype=Float64),
        Field(name="tga", dtype=Float64),
        Field(name="reverse_repo", dtype=Float64),
        Field(name="rbi_liquidity", dtype=Float64),
        Field(name="laf", dtype=Float64),
        Field(name="msf", dtype=Float64),
        Field(name="sdf", dtype=Float64),
        Field(name="fii_flows", dtype=Float64),
        Field(name="dii_flows", dtype=Float64),
    ],
    source=liquidity_diagnostics_source,
    online=True,
    description="Named liquidity features consumed by Phase 7 diagnostics.",
    tags={"phase": "integration-stabilization", "version": "v1"},
)


market_features = FeatureService(
    name="market_features",
    features=[daily_market_metrics],
    tags={"phase": "2", "version": "v1"},
)

macro_features = FeatureService(
    name="macro_features",
    features=[macro_liquidity_indicators],
    tags={"phase": "2", "version": "v1"},
)

crypto_features = FeatureService(
    name="crypto_features",
    features=[crypto_onchain_metrics],
    tags={"phase": "2", "version": "v1"},
)

liquidity_features = FeatureService(
    name="liquidity_features",
    features=[liquidity_diagnostics],
    tags={"phase": "integration-stabilization", "version": "v1"},
)


FEATURE_VIEWS = [
    daily_market_metrics,
    macro_liquidity_indicators,
    crypto_onchain_metrics,
    liquidity_diagnostics,
]

ENTITIES = [
    asset,
    indicator,
]

FEATURE_SERVICES = [
    market_features,
    macro_features,
    crypto_features,
    liquidity_features,
]
