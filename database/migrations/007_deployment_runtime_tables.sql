-- Deployment compatibility runtime tables.
-- These tables complete persistence paths referenced by the frozen analytics code
-- and n8n workflows without changing earlier phase migrations.

CREATE TABLE IF NOT EXISTS breadth_metrics (
    timestamp TIMESTAMPTZ NOT NULL,
    leading_diffusion_index NUMERIC(8, 6) NOT NULL CHECK (leading_diffusion_index BETWEEN -1.0 AND 1.0),
    advance_decline_ratio NUMERIC(18, 6) NOT NULL CHECK (advance_decline_ratio >= 0.0),
    new_high_new_low_ratio NUMERIC(8, 6) NOT NULL CHECK (new_high_new_low_ratio BETWEEN 0.0 AND 1.0),
    percent_above_50_sma NUMERIC(8, 6) NOT NULL CHECK (percent_above_50_sma BETWEEN 0.0 AND 1.0),
    percent_above_200_sma NUMERIC(8, 6) NOT NULL CHECK (percent_above_200_sma BETWEEN 0.0 AND 1.0),
    equal_weight_vs_cap_weight_spread NUMERIC(18, 8) NOT NULL,
    hhi_concentration_score NUMERIC(8, 6) NOT NULL CHECK (hhi_concentration_score BETWEEN 0.0 AND 1.0),
    advance_decline_line NUMERIC(18, 6) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_breadth_metrics_timestamp
    ON breadth_metrics (timestamp DESC);

CREATE TABLE IF NOT EXISTS macro_regime_classifications (
    timestamp TIMESTAMPTZ NOT NULL,
    regime_state VARCHAR(20) NOT NULL,
    regime_probability NUMERIC(8, 6) NOT NULL CHECK (regime_probability BETWEEN 0.0 AND 1.0),
    leading_diffusion_index NUMERIC(8, 6) NOT NULL CHECK (leading_diffusion_index BETWEEN -1.0 AND 1.0),
    hhi_concentration_score NUMERIC(8, 6) NOT NULL CHECK (hhi_concentration_score BETWEEN 0.0 AND 1.0),
    stress_score NUMERIC(8, 6) NOT NULL CHECK (stress_score BETWEEN 0.0 AND 100.0)
);

CREATE INDEX IF NOT EXISTS idx_macro_regime_timestamp
    ON macro_regime_classifications (timestamp DESC, regime_state);

CREATE TABLE IF NOT EXISTS scenario_outputs (
    timestamp TIMESTAMPTZ NOT NULL,
    scenario_name VARCHAR(64) NOT NULL,
    novelty_score NUMERIC(8, 4) NOT NULL CHECK (novelty_score BETWEEN 0.0 AND 100.0),
    systemic_stress_12m NUMERIC(8, 6) NOT NULL CHECK (systemic_stress_12m BETWEEN 0.0 AND 1.0),
    payload JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS idx_scenario_outputs_timestamp
    ON scenario_outputs (timestamp DESC, scenario_name);

CREATE TABLE IF NOT EXISTS governance_outputs (
    timestamp TIMESTAMPTZ NOT NULL,
    decision VARCHAR(64) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS idx_governance_outputs_timestamp
    ON governance_outputs (timestamp DESC, severity);

CREATE TABLE IF NOT EXISTS audit_outputs (
    timestamp TIMESTAMPTZ NOT NULL,
    audit_type VARCHAR(64) NOT NULL,
    additive_valid BOOLEAN NOT NULL DEFAULT TRUE,
    metric_value NUMERIC(18, 8),
    payload JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_outputs_timestamp
    ON audit_outputs (timestamp DESC, audit_type);
