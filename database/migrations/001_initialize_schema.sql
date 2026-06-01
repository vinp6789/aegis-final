-- Phase 1: TimescaleDB Schema
-- Source of truth: CODEX_EXECUTION_PLAYBOOK_FINAL + MASTER_IMPLEMENTATION_SPEC_FINAL.
-- Scope: extension and base registries only.

--CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

CREATE TABLE IF NOT EXISTS asset_registry (
    asset_id VARCHAR(50) PRIMARY KEY,
    asset_name VARCHAR(100) NOT NULL,
    asset_class VARCHAR(50) NOT NULL,
    region VARCHAR(50) NOT NULL,
    data_provider VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_asset_lookup
    ON asset_registry (asset_class, region)
    WHERE is_active = TRUE;
