-- Phase 1: TimescaleDB Schema
-- Reserved migration slot from MASTER_IMPLEMENTATION_SPEC_FINAL.
--
-- The frozen Phase 1 DDL defines the core TimescaleDB tables required by the
-- playbook and does not define additional backtesting table structures.
-- This file intentionally performs no schema changes to avoid inventing
-- future-phase architecture.

DO $$
BEGIN
    RAISE NOTICE '006_create_backtest_hypertables.sql is reserved; no Phase 1 backtest tables are defined.';
END;
$$;
