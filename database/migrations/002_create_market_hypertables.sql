-- Phase 1: TimescaleDB Schema
-- Market, macro, crypto on-chain, and ingestion health hypertables.

CREATE TABLE IF NOT EXISTS daily_market_metrics (
    timestamp TIMESTAMPTZ NOT NULL,
    asset_id VARCHAR(50) REFERENCES asset_registry(asset_id),
    open_price NUMERIC(24, 8) NOT NULL,
    high_price NUMERIC(24, 8) NOT NULL,
    low_price NUMERIC(24, 8) NOT NULL,
    close_price NUMERIC(24, 8) NOT NULL,
    volume NUMERIC(24, 8) CHECK (volume >= 0.0),
    open_interest NUMERIC(24, 8) CHECK (open_interest >= 0.0),
    realized_volatility_30d NUMERIC(8, 6),
    market_cap NUMERIC(30, 2) CHECK (market_cap >= 0.0),
    CONSTRAINT chk_daily_market_prices_positive CHECK (
        open_price > 0.0
        AND high_price > 0.0
        AND low_price > 0.0
        AND close_price > 0.0
    ),
    CONSTRAINT chk_daily_market_high_low CHECK (high_price >= low_price)
);

/*SELECT create_hypertable(
    'daily_market_metrics',
    'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);*/

CREATE INDEX IF NOT EXISTS idx_market_asset_time
    ON daily_market_metrics (asset_id, timestamp DESC);

ALTER TABLE daily_market_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id'
);

SELECT add_compression_policy(
    'daily_market_metrics',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

SELECT add_retention_policy(
    'daily_market_metrics',
    INTERVAL '730 days',
    if_not_exists => TRUE
);

CREATE TABLE IF NOT EXISTS macro_liquidity_indicators (
    timestamp TIMESTAMPTZ NOT NULL,
    indicator_code VARCHAR(50) NOT NULL,
    value NUMERIC(20, 6) NOT NULL,
    revised BOOLEAN DEFAULT FALSE,
    release_date TIMESTAMPTZ NOT NULL
);

/*SELECT create_hypertable(
    'macro_liquidity_indicators',
    'timestamp',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);*/

CREATE INDEX IF NOT EXISTS idx_indicator_time
    ON macro_liquidity_indicators (indicator_code, timestamp DESC);

ALTER TABLE macro_liquidity_indicators SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'indicator_code'
);

SELECT add_compression_policy(
    'macro_liquidity_indicators',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

CREATE TABLE IF NOT EXISTS crypto_onchain_metrics (
    timestamp TIMESTAMPTZ NOT NULL,
    asset_id VARCHAR(50) REFERENCES asset_registry(asset_id),
    mvrv_z_score NUMERIC(8, 4),
    nupl NUMERIC(8, 4),
    exchange_reserve_btc NUMERIC(24, 8) CHECK (exchange_reserve_btc >= 0.0),
    stablecoin_inflow_volume NUMERIC(24, 8) CHECK (stablecoin_inflow_volume >= 0.0),
    active_addresses INT CHECK (active_addresses >= 0),
    ssr_ratio NUMERIC(10, 4)
);

/*SELECT create_hypertable(
    'crypto_onchain_metrics',
    'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);*/

CREATE INDEX IF NOT EXISTS idx_crypto_time
    ON crypto_onchain_metrics (asset_id, timestamp DESC);

ALTER TABLE crypto_onchain_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id'
);

SELECT add_compression_policy(
    'crypto_onchain_metrics',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

CREATE TABLE IF NOT EXISTS ingestion_source_health (
    timestamp TIMESTAMPTZ NOT NULL,
    source_name VARCHAR(50) NOT NULL,
    availability_rate NUMERIC(5, 4) NOT NULL,
    freshness_seconds INT NOT NULL,
    missing_value_ratio NUMERIC(5, 4) NOT NULL,
    average_latency_ms INT NOT NULL,
    validation_success_rate NUMERIC(5, 4) NOT NULL,
    source_health_score NUMERIC(5, 2) NOT NULL,
    PRIMARY KEY (timestamp, source_name),
    CONSTRAINT chk_source_health_rates CHECK (
        availability_rate BETWEEN 0.0 AND 1.0
        AND missing_value_ratio BETWEEN 0.0 AND 1.0
        AND validation_success_rate BETWEEN 0.0 AND 1.0
    ),
    CONSTRAINT chk_source_health_non_negative CHECK (
        freshness_seconds >= 0
        AND average_latency_ms >= 0
        AND source_health_score BETWEEN 0.0 AND 100.0
    )
);

/*SELECT create_hypertable(
    'ingestion_source_health',
    'timestamp',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);*/

CREATE INDEX IF NOT EXISTS idx_source_health_history
    ON ingestion_source_health (source_name, timestamp DESC);
