SELECT create_hypertable('daily_market_metrics', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('macro_liquidity_indicators', 'timestamp', chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('crypto_onchain_metrics', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('ingestion_source_health', 'timestamp', chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE, migrate_data => TRUE);

SELECT create_hypertable('india_liquidity_flows', 'timestamp', chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('crypto_market_metrics_v2', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('stablecoin_liquidity_growth', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE, migrate_data => TRUE);

SELECT create_hypertable('probability_matrix_outputs_v3', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('data_quality_exceptions', 'timestamp', chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE, migrate_data => TRUE);

ALTER TABLE daily_market_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id'
);

ALTER TABLE macro_liquidity_indicators SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'indicator_code'
);

ALTER TABLE crypto_onchain_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id'
);

ALTER TABLE stablecoin_liquidity_growth SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_symbol'
);

SELECT add_compression_policy('daily_market_metrics', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_compression_policy('macro_liquidity_indicators', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_compression_policy('crypto_onchain_metrics', INTERVAL '90 days', if_not_exists => TRUE);
SELECT add_compression_policy('stablecoin_liquidity_growth', INTERVAL '90 days', if_not_exists => TRUE);

SELECT add_retention_policy('daily_market_metrics', INTERVAL '730 days', if_not_exists => TRUE);
SELECT add_retention_policy('data_quality_exceptions', INTERVAL '180 days', if_not_exists => TRUE);
