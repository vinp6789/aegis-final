-- Phase 1: TimescaleDB Schema
-- Data quality exception hypertable and dynamic feature lifecycle registry.

CREATE TABLE IF NOT EXISTS data_quality_exceptions (
    timestamp TIMESTAMPTZ NOT NULL,
    source_name VARCHAR(50) NOT NULL,
    field_name VARCHAR(100) NOT NULL,
    exception_type VARCHAR(50) NOT NULL,
    bad_value_raw TEXT,
    severity VARCHAR(20) NOT NULL,
    CONSTRAINT chk_quality_exception_severity CHECK (
        severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
    )
);

/*SELECT create_hypertable(
    'data_quality_exceptions',
    'timestamp',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);*/

CREATE INDEX IF NOT EXISTS idx_quality_exceptions
    ON data_quality_exceptions (source_name, exception_type, timestamp DESC);

SELECT add_retention_policy(
    'data_quality_exceptions',
    INTERVAL '180 days',
    if_not_exists => TRUE
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type
        WHERE typname = 'feature_lifecycle_state'
    ) THEN
        CREATE TYPE feature_lifecycle_state AS ENUM (
            'PROPOSED',
            'WATCH',
            'PROMOTED',
            'DEMOTED',
            'RETIRED'
        );
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS feature_lifecycle_registry (
    feature_name VARCHAR(100) PRIMARY KEY,
    current_state feature_lifecycle_state NOT NULL DEFAULT 'PROPOSED',
    target_scope VARCHAR(50) NOT NULL,
    primary_horizon_months INT NOT NULL CHECK (primary_horizon_months IN (1, 3, 6, 9, 12)),
    secondary_horizon_months INT NOT NULL CHECK (secondary_horizon_months IN (1, 3, 6, 9, 12)),
    current_score NUMERIC(5, 2) NOT NULL,
    peak_score NUMERIC(5, 2) NOT NULL,
    last_evaluated TIMESTAMPTZ NOT NULL,
    consecutive_monthly_failures INT DEFAULT 0 CHECK (consecutive_monthly_failures >= 0),
    demoted_at TIMESTAMPTZ,
    retirement_reason TEXT,
    CONSTRAINT chk_feature_scores_bounds CHECK (
        current_score BETWEEN 0.0 AND 100.0
        AND peak_score BETWEEN 0.0 AND 100.0
    )
);

CREATE INDEX IF NOT EXISTS idx_feature_state_v3
    ON feature_lifecycle_registry (current_state, target_scope);
