\set ON_ERROR_STOP on

-- Run after applying database/migrations/001-006 in order.
-- Validates hypertable creation, chunk intervals, compression, and retention jobs.

DO $$
DECLARE
    missing_hypertables TEXT[];
BEGIN
    SELECT ARRAY_AGG(required_table)
    INTO missing_hypertables
    FROM (
        VALUES
            ('daily_market_metrics'),
            ('macro_liquidity_indicators'),
            ('crypto_onchain_metrics'),
            ('ingestion_source_health'),
            ('india_liquidity_flows'),
            ('crypto_market_metrics_v2'),
            ('stablecoin_liquidity_growth'),
            ('data_quality_exceptions'),
            ('probability_matrix_outputs_v3')
    ) AS required(required_table)
    WHERE NOT EXISTS (
        SELECT 1
        FROM timescaledb_information.hypertables h
        WHERE h.hypertable_schema = 'public'
          AND h.hypertable_name = required.required_table
    );

    IF missing_hypertables IS NOT NULL THEN
        RAISE EXCEPTION 'Missing hypertables: %', missing_hypertables;
    END IF;
END;
$$;

DO $$
DECLARE
    invalid_chunks TEXT[];
BEGIN
    SELECT ARRAY_AGG(expected.hypertable_name || ' expected ' || expected.chunk_interval)
    INTO invalid_chunks
    FROM (
        VALUES
            ('daily_market_metrics', INTERVAL '7 days'),
            ('macro_liquidity_indicators', INTERVAL '30 days'),
            ('crypto_onchain_metrics', INTERVAL '7 days'),
            ('ingestion_source_health', INTERVAL '30 days'),
            ('india_liquidity_flows', INTERVAL '30 days'),
            ('crypto_market_metrics_v2', INTERVAL '7 days'),
            ('stablecoin_liquidity_growth', INTERVAL '7 days'),
            ('data_quality_exceptions', INTERVAL '30 days'),
            ('probability_matrix_outputs_v3', INTERVAL '7 days')
    ) AS expected(hypertable_name, chunk_interval)
    WHERE NOT EXISTS (
        SELECT 1
        FROM _timescaledb_catalog.hypertable h
        JOIN _timescaledb_catalog.dimension d
          ON d.hypertable_id = h.id
        WHERE h.schema_name = 'public'
          AND h.table_name = expected.hypertable_name
          AND d.column_name = 'timestamp'
          AND d.interval_length = (
              EXTRACT(EPOCH FROM expected.chunk_interval) * 1000000
          )::BIGINT
    );

    IF invalid_chunks IS NOT NULL THEN
        RAISE EXCEPTION 'Invalid or missing hypertable chunk intervals: %', invalid_chunks;
    END IF;
END;
$$;

DO $$
DECLARE
    missing_compression TEXT[];
BEGIN
    SELECT ARRAY_AGG(required_table)
    INTO missing_compression
    FROM (
        VALUES
            ('daily_market_metrics'),
            ('macro_liquidity_indicators'),
            ('crypto_onchain_metrics'),
            ('stablecoin_liquidity_growth')
    ) AS required(required_table)
    WHERE NOT EXISTS (
        SELECT 1
        FROM timescaledb_information.hypertables h
        WHERE h.hypertable_schema = 'public'
          AND h.hypertable_name = required.required_table
          AND h.compression_enabled IS TRUE
    );

    IF missing_compression IS NOT NULL THEN
        RAISE EXCEPTION 'Compression is not enabled for: %', missing_compression;
    END IF;
END;
$$;

DO $$
DECLARE
    missing_compression_policy_tables TEXT[];
    missing_retention_policy_tables TEXT[];
BEGIN
    SELECT ARRAY_AGG(required_table)
    INTO missing_compression_policy_tables
    FROM (
        VALUES
            ('daily_market_metrics'),
            ('macro_liquidity_indicators'),
            ('crypto_onchain_metrics'),
            ('stablecoin_liquidity_growth')
    ) AS required(required_table)
    WHERE NOT EXISTS (
        SELECT 1
        FROM _timescaledb_config.bgw_job j
        JOIN _timescaledb_catalog.hypertable h
          ON h.id = (j.config ->> 'hypertable_id')::INTEGER
        WHERE h.schema_name = 'public'
          AND h.table_name = required.required_table
          AND j.proc_name = 'policy_compression'
    );

    IF missing_compression_policy_tables IS NOT NULL THEN
        RAISE EXCEPTION 'Missing compression policy job for: %', missing_compression_policy_tables;
    END IF;

    SELECT ARRAY_AGG(required_table)
    INTO missing_retention_policy_tables
    FROM (
        VALUES
            ('daily_market_metrics'),
            ('data_quality_exceptions')
    ) AS required(required_table)
    WHERE NOT EXISTS (
        SELECT 1
        FROM _timescaledb_config.bgw_job j
        JOIN _timescaledb_catalog.hypertable h
          ON h.id = (j.config ->> 'hypertable_id')::INTEGER
        WHERE h.schema_name = 'public'
          AND h.table_name = required.required_table
          AND j.proc_name = 'policy_retention'
    );

    IF missing_retention_policy_tables IS NOT NULL THEN
        RAISE EXCEPTION 'Missing retention policy job for: %', missing_retention_policy_tables;
    END IF;
END;
$$;
