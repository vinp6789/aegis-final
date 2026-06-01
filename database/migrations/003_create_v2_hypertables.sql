-- Phase 1: TimescaleDB Schema
-- V2 liquidity, crypto market, and stablecoin liquidity hypertables.

CREATE TABLE IF NOT EXISTS india_liquidity_flows (
    timestamp TIMESTAMPTZ NOT NULL,
    rbi_total_assets NUMERIC(24, 2),
    net_laf_absorption NUMERIC(24, 2),
    marginal_standing_facility NUMERIC(24, 2),
    standing_deposit_facility NUMERIC(24, 2),
    bank_credit_growth_yoy NUMERIC(6, 4) NOT NULL,
    bank_deposit_growth_yoy NUMERIC(6, 4) NOT NULL,
    fii_net_flow_usd NUMERIC(20, 2),
    dii_net_flow_inr NUMERIC(24, 2),
    CONSTRAINT chk_india_liquidity_non_negative CHECK (
        (rbi_total_assets IS NULL OR rbi_total_assets >= 0.0)
        AND (marginal_standing_facility IS NULL OR marginal_standing_facility >= 0.0)
        AND (standing_deposit_facility IS NULL OR standing_deposit_facility >= 0.0)
    )
);

/*SELECT create_hypertable(
    'india_liquidity_flows',
    'timestamp',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);*/

CREATE INDEX IF NOT EXISTS idx_in_liquidity
    ON india_liquidity_flows (timestamp DESC);

CREATE TABLE IF NOT EXISTS crypto_market_metrics_v2 (
    timestamp TIMESTAMPTZ NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    market_cap NUMERIC(30, 2) NOT NULL,
    close_price NUMERIC(24, 8) NOT NULL,
    volume_24h NUMERIC(30, 2) NOT NULL,
    CONSTRAINT chk_crypto_market_v2_non_negative CHECK (
        market_cap >= 0.0
        AND close_price > 0.0
        AND volume_24h >= 0.0
    )
);

/*SELECT create_hypertable(
    'crypto_market_metrics_v2',
    'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);*/

CREATE INDEX IF NOT EXISTS idx_crypto_v2_lookup
    ON crypto_market_metrics_v2 (ticker, timestamp DESC);

CREATE TABLE IF NOT EXISTS stablecoin_liquidity_growth (
    timestamp TIMESTAMPTZ NOT NULL,
    token_symbol VARCHAR(15) NOT NULL,
    circulating_supply NUMERIC(24, 4) NOT NULL,
    daily_growth_pct NUMERIC(8, 6) NOT NULL,
    weekly_growth_pct NUMERIC(8, 6) NOT NULL,
    monthly_growth_pct NUMERIC(8, 6) NOT NULL,
    CONSTRAINT chk_stablecoin_supply_positive CHECK (circulating_supply > 0.0)
);

/*SELECT create_hypertable(
    'stablecoin_liquidity_growth',
    'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);*/

CREATE INDEX IF NOT EXISTS idx_stablecoin_lookup
    ON stablecoin_liquidity_growth (token_symbol, timestamp DESC);

ALTER TABLE stablecoin_liquidity_growth SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_symbol'
);

SELECT add_compression_policy(
    'stablecoin_liquidity_growth',
    INTERVAL '90 days',
    if_not_exists => TRUE
);
