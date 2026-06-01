-- Phase 1: TimescaleDB Schema
-- V3 consolidated probability matrix hypertable.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type
        WHERE typname = 'probability_risk_regime'
    ) THEN
        CREATE TYPE probability_risk_regime AS ENUM (
            'LOW_RISK',
            'WATCH',
            'ELEVATED',
            'HIGH_RISK',
            'CRISIS'
        );
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS probability_matrix_outputs_v3 (
    timestamp TIMESTAMPTZ NOT NULL,
    target_scope VARCHAR(50) NOT NULL,
    crash_prob_1m NUMERIC(5, 4) NOT NULL,
    crash_prob_3m NUMERIC(5, 4) NOT NULL,
    crash_prob_6m NUMERIC(5, 4) NOT NULL,
    crash_prob_9m NUMERIC(5, 4) NOT NULL,
    crash_prob_12m NUMERIC(5, 4) NOT NULL,
    pump_prob_1m NUMERIC(5, 4) NOT NULL,
    pump_prob_3m NUMERIC(5, 4) NOT NULL,
    pump_prob_6m NUMERIC(5, 4) NOT NULL,
    pump_prob_9m NUMERIC(5, 4) NOT NULL,
    pump_prob_12m NUMERIC(5, 4) NOT NULL,
    ensemble_disagreement_score NUMERIC(5, 4) NOT NULL,
    early_warning_score NUMERIC(5, 2) NOT NULL,
    confidence_score NUMERIC(5, 4) NOT NULL,
    current_regime probability_risk_regime NOT NULL,
    CONSTRAINT chk_probability_matrix_bounds CHECK (
        crash_prob_1m BETWEEN 0.0 AND 1.0
        AND crash_prob_3m BETWEEN 0.0 AND 1.0
        AND crash_prob_6m BETWEEN 0.0 AND 1.0
        AND crash_prob_9m BETWEEN 0.0 AND 1.0
        AND crash_prob_12m BETWEEN 0.0 AND 1.0
        AND pump_prob_1m BETWEEN 0.0 AND 1.0
        AND pump_prob_3m BETWEEN 0.0 AND 1.0
        AND pump_prob_6m BETWEEN 0.0 AND 1.0
        AND pump_prob_9m BETWEEN 0.0 AND 1.0
        AND pump_prob_12m BETWEEN 0.0 AND 1.0
        AND ensemble_disagreement_score BETWEEN 0.0 AND 1.0
        AND confidence_score BETWEEN 0.0 AND 1.0
    ),
    CONSTRAINT chk_probability_ews_bounds CHECK (
        early_warning_score BETWEEN 0.0 AND 100.0
    )
);

/*SELECT create_hypertable(
    'probability_matrix_outputs_v3',
    'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);*/

CREATE INDEX IF NOT EXISTS idx_prob_matrix_v3
    ON probability_matrix_outputs_v3 (target_scope, current_regime, timestamp DESC);
