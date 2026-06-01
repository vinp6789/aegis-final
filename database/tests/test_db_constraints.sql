\set ON_ERROR_STOP on

-- Run after applying database/migrations/001-006 in order.
-- Validates Phase 1 defaults, timezone-aware columns, and bounded constraints.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_extension
        WHERE extname = 'timescaledb'
    ) THEN
        RAISE EXCEPTION 'TimescaleDB extension is not installed';
    END IF;
END;
$$;

DO $$
DECLARE
    invalid_timestamp_columns INTEGER;
BEGIN
    SELECT COUNT(*)
    INTO invalid_timestamp_columns
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name IN (
          'asset_registry',
          'daily_market_metrics',
          'macro_liquidity_indicators',
          'crypto_onchain_metrics',
          'ingestion_source_health',
          'india_liquidity_flows',
          'crypto_market_metrics_v2',
          'stablecoin_liquidity_growth',
          'data_quality_exceptions',
          'feature_lifecycle_registry',
          'probability_matrix_outputs_v3'
      )
      AND column_name IN ('timestamp', 'created_at', 'release_date', 'last_evaluated', 'demoted_at')
      AND data_type <> 'timestamp with time zone';

    IF invalid_timestamp_columns <> 0 THEN
        RAISE EXCEPTION 'Found % timestamp columns that are not TIMESTAMPTZ', invalid_timestamp_columns;
    END IF;
END;
$$;

DO $$
DECLARE
    observed_is_active BOOLEAN;
    observed_created_at TIMESTAMPTZ;
    observed_current_state feature_lifecycle_state;
    observed_failures INTEGER;
BEGIN
    INSERT INTO asset_registry (
        asset_id,
        asset_name,
        asset_class,
        region,
        data_provider
    ) VALUES (
        '__constraint_test_asset__',
        'Constraint Test Asset',
        'CRYPTO',
        'CRYPTO',
        'UNIT_TEST'
    )
    RETURNING is_active, created_at
    INTO observed_is_active, observed_created_at;

    IF observed_is_active IS DISTINCT FROM TRUE OR observed_created_at IS NULL THEN
        RAISE EXCEPTION 'asset_registry defaults failed';
    END IF;

    INSERT INTO feature_lifecycle_registry (
        feature_name,
        target_scope,
        primary_horizon_months,
        secondary_horizon_months,
        current_score,
        peak_score,
        last_evaluated
    ) VALUES (
        '__constraint_test_feature__',
        'GLOBAL',
        1,
        3,
        10.0,
        20.0,
        NOW()
    )
    RETURNING current_state, consecutive_monthly_failures
    INTO observed_current_state, observed_failures;

    IF observed_current_state <> 'PROPOSED' OR observed_failures <> 0 THEN
        RAISE EXCEPTION 'feature_lifecycle_registry defaults failed';
    END IF;
END;
$$;

DO $$
DECLARE
    raised_check_violation BOOLEAN := FALSE;
BEGIN
    BEGIN
        INSERT INTO daily_market_metrics (
            timestamp,
            asset_id,
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
            open_interest,
            market_cap
        ) VALUES (
            NOW(),
            '__constraint_test_asset__',
            100.0,
            101.0,
            99.0,
            100.5,
            -1.0,
            0.0,
            1000000.0
        );
    EXCEPTION
        WHEN check_violation THEN
            raised_check_violation := TRUE;
    END;

    IF NOT raised_check_violation THEN
        RAISE EXCEPTION 'daily_market_metrics accepted a negative volume';
    END IF;
END;
$$;

DO $$
DECLARE
    raised_check_violation BOOLEAN := FALSE;
BEGIN
    BEGIN
        INSERT INTO ingestion_source_health (
            timestamp,
            source_name,
            availability_rate,
            freshness_seconds,
            missing_value_ratio,
            average_latency_ms,
            validation_success_rate,
            source_health_score
        ) VALUES (
            NOW(),
            'UNIT_TEST_SOURCE',
            1.2,
            0,
            0.0,
            1,
            1.0,
            95.0
        );
    EXCEPTION
        WHEN check_violation THEN
            raised_check_violation := TRUE;
    END;

    IF NOT raised_check_violation THEN
        RAISE EXCEPTION 'ingestion_source_health accepted an availability_rate outside [0, 1]';
    END IF;
END;
$$;

DO $$
DECLARE
    raised_check_violation BOOLEAN := FALSE;
BEGIN
    BEGIN
        INSERT INTO stablecoin_liquidity_growth (
            timestamp,
            token_symbol,
            circulating_supply,
            daily_growth_pct,
            weekly_growth_pct,
            monthly_growth_pct
        ) VALUES (
            NOW(),
            'USDT',
            0.0,
            0.0,
            0.0,
            0.0
        );
    EXCEPTION
        WHEN check_violation THEN
            raised_check_violation := TRUE;
    END;

    IF NOT raised_check_violation THEN
        RAISE EXCEPTION 'stablecoin_liquidity_growth accepted non-positive supply';
    END IF;
END;
$$;

DO $$
DECLARE
    raised_check_violation BOOLEAN := FALSE;
BEGIN
    BEGIN
        INSERT INTO probability_matrix_outputs_v3 (
            timestamp,
            target_scope,
            crash_prob_1m,
            crash_prob_3m,
            crash_prob_6m,
            crash_prob_9m,
            crash_prob_12m,
            pump_prob_1m,
            pump_prob_3m,
            pump_prob_6m,
            pump_prob_9m,
            pump_prob_12m,
            ensemble_disagreement_score,
            early_warning_score,
            confidence_score,
            current_regime
        ) VALUES (
            NOW(),
            'GLOBAL',
            1.1,
            0.2,
            0.3,
            0.4,
            0.5,
            0.1,
            0.2,
            0.3,
            0.4,
            0.5,
            0.1,
            50.0,
            0.9,
            'WATCH'
        );
    EXCEPTION
        WHEN check_violation THEN
            raised_check_violation := TRUE;
    END;

    IF NOT raised_check_violation THEN
        RAISE EXCEPTION 'probability_matrix_outputs_v3 accepted a probability outside [0, 1]';
    END IF;
END;
$$;

ROLLBACK;
