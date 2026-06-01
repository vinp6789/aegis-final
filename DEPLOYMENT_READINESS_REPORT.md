# Deployment Readiness Report

## 1. Final System Architecture Summary

Aegis is organized as a local-first forecasting and early-warning platform with:

- TimescaleDB/PostgreSQL persistence for market, liquidity, quality, lifecycle, and probability outputs.
- Feast feature store definitions for offline/online feature access.
- Independent ingestion adapters with quality validation and exception logging.
- Analytics engines for discovery, validation, backtesting, walk-forward calibration, liquidity, breadth, regimes, probability aggregation, regime memory, scenarios, governance, audit, explainability, sector intelligence, and crypto intelligence.
- n8n Community Edition workflows for collection, feature engineering, model training, probability generation, scenarios, reporting, governance, and audit/explainability orchestration.

## 2. Completed Phases

- Phase 1: TimescaleDB Schema
- Phase 2: Feast Feature Store
- Phase 3: Ingestion Layer
- Phase 4: Leading Indicator Discovery Engine
- Phase 5: Backtesting Engine
- Phase 6: Walk Forward Engine
- Phase 7: Liquidity Engine
- Phase 8: Breadth Engine
- Phase 9: Probability Engine
- Phase 10: Regime Memory Engine
- Phase 11: Scenario Engine
- Phase 12: Forecast Audit Engine
- Phase 13: Governance Engine
- Phase 14: India Sector Engine
- Phase 15: Crypto Engine
- Phase 16: Explainability Engine
- Phase 17: Alerting Layer n8n workflows

## 3. Completed Workflows

- `n8n/workflow_1_data_collection.json`
- `n8n/workflow_2_feature_engineering.json`
- `n8n/workflow_3_model_training.json`
- `n8n/workflow_4_probability_generation.json`
- `n8n/workflow_5_scenario_generation.json`
- `n8n/workflow_6_reporting.json`
- `n8n/workflow_7_governance.json`
- `n8n/workflow_8_audit_explainability.json`

## 4. Known Limitations

- Several analytics modules use deterministic local implementations intended for zero-cost runtime operation.
- n8n workflows are valid JSON orchestration templates but require real credentials, container service names, and environment URLs before production execution.
- Workflow command nodes assume the analytics package is importable from `AEGIS_WORKDIR`.
- Some workflow persistence uses `data_quality_exceptions` as a structured log sink because no dedicated frozen tables exist for those outputs.
- Full live TimescaleDB, Feast, and n8n end-to-end execution was not performed in this audit.

## 5. Technical Debt

- Phase 4 statistical routines currently use NumPy-based ADF, cointegration, and Granger-style implementations.
- Recommended future replacements are `statsmodels.tsa.stattools.adfuller`, `statsmodels.tsa.vector_ar.vecm.coint_johansen`, and `statsmodels.tsa.stattools.grangercausalitytests`.
- If custom Granger logic remains, replace approximate F-test p-values with `scipy.stats.f.sf`.
- Transfer entropy should be benchmarked against a dedicated information-theory implementation if one is later introduced.
- See `docs/TECHNICAL_DEBT.md`.

## 6. Missing Persistence Tables

These adapters reference tables that are not defined in frozen migrations:

- `breadth_metrics`
- `macro_regime_classifications`

No schema should be added until an explicit phase or migration instruction permits it.

## 7. Runtime Dependencies

- Python 3.11 or compatible runtime
- NumPy
- SciPy, optional but used when available by governance optimization
- Feast
- psycopg2/PostgreSQL client support
- PostgreSQL with TimescaleDB extension
- n8n Community Edition
- Docker and Docker Compose for VPS/local service orchestration

## 8. Local Deployment Steps

1. Start PostgreSQL/TimescaleDB locally.
2. Apply migrations in `database/migrations` in numeric order.
3. Configure database credentials from `database/db_config.yaml`.
4. Install Python dependencies in the local runtime.
5. Configure Feast in `aegis-platform/feature_store.yaml`.
6. Run Feast apply from the `aegis-platform` directory.
7. Configure n8n credentials named `Aegis TimescaleDB`.
8. Import workflows from `n8n/workflow_*.json`.
9. Set environment variables used by workflows, including adapter URLs and alert webhook URLs.
10. Run targeted workflow tests manually before activating schedules.

## 9. VPS Deployment Steps

1. Provision a Linux VPS with Docker and Docker Compose.
2. Create services for TimescaleDB, n8n, and the Python analytics/ingestion runtime.
3. Mount the repository into the analytics container at the path referenced by `AEGIS_WORKDIR`.
4. Store PostgreSQL credentials and webhook secrets as environment variables.
5. Apply database migrations once.
6. Run Feast apply once after database connectivity is verified.
7. Import all n8n workflows.
8. Configure n8n credentials for PostgreSQL and alert webhooks.
9. Activate workflows after smoke checks.
10. Enable persistent volumes for TimescaleDB and n8n.

## 10. n8n Startup Instructions

1. Start n8n Community Edition.
2. Set timezone to UTC.
3. Configure PostgreSQL credential `Aegis TimescaleDB`.
4. Import workflows 1 through 8.
5. Set required environment variables:
   - `AEGIS_WORKDIR`
   - `AEGIS_NSE_ADAPTER_URL`
   - `AEGIS_RBI_ADAPTER_URL`
   - `AEGIS_STABLECOIN_ADAPTER_URL`
   - `AEGIS_REPORT_WEBHOOK_URL`
   - `AEGIS_TELEGRAM_WEBHOOK_URL`
   - `AEGIS_EMAIL_WEBHOOK_URL`
   - `AEGIS_GOVERNANCE_WEBHOOK_URL`
   - `AEGIS_KILL_SWITCH_WEBHOOK_URL`
   - `AEGIS_AUDIT_ALERT_WEBHOOK_URL`
6. Run each workflow manually once.
7. Activate workflows after successful manual execution.

## 11. PostgreSQL/TimescaleDB Startup Instructions

1. Start PostgreSQL with TimescaleDB extension enabled.
2. Create the Aegis database and user.
3. Confirm `CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE`.
4. Apply migrations:
   - `001_initialize_schema.sql`
   - `002_create_market_hypertables.sql`
   - `003_create_v2_hypertables.sql`
   - `004_create_v3_hypertables.sql`
   - `005_create_discovery_hypertables.sql`
   - `006_create_backtest_hypertables.sql`
5. Run database constraint tests before enabling live workflows.
6. Confirm hypertables and indexes are present.

## 12. Feast Startup Instructions

1. Enter the `aegis-platform` directory.
2. Verify `feature_store.yaml` points to the local registry and PostgreSQL offline store.
3. Export database credentials required by Feast.
4. Run `feast apply`.
5. Run a small historical retrieval smoke test.
6. Keep Feast registry files on persistent storage if deployed in containers.

## 13. Telegram Alert Setup

1. Create a Telegram bot with BotFather.
2. Store bot token in the alert router or n8n environment.
3. Identify the target chat ID.
4. Configure `AEGIS_TELEGRAM_WEBHOOK_URL` to route report/governance/audit alerts.
5. Send a manual test message before activating scheduled alerts.
6. Keep token outside source control.

## 14. Recommended Cron Schedules

- Workflow 1 Data Collection: hourly UTC.
- Workflow 2 Feature Engineering: daily after ingestion completion.
- Workflow 3 Model Training: daily trigger with governance gate; monthly full retraining if required.
- Workflow 4 Probability Generation: daily after feature engineering.
- Workflow 5 Scenario Generation: daily after probability generation.
- Workflow 6 Reporting: daily after scenarios; weekly summary can reuse the same workflow with a weekly trigger copy.
- Workflow 7 Governance: daily after probability/scenario generation.
- Workflow 8 Audit Explainability: daily after governance and when realizations are available.

## 15. Recovery and Restart Procedures

- Restart TimescaleDB first, then analytics services, then n8n.
- If n8n fails, leave database running and restart n8n with persisted workflow volume.
- If ingestion fails, inspect `data_quality_exceptions` and `ingestion_source_health`.
- If probability generation fails, rerun workflows 2, 4, and 5 in order.
- If governance alerts fire unexpectedly, inspect Workflow 7 logs and recent `probability_matrix_outputs_v3` rows.
- If Feast retrieval fails, rerun `feast apply` and verify PostgreSQL connectivity.
- If command nodes fail, verify `AEGIS_WORKDIR` and Python import paths.
- If database recovery is required, restore TimescaleDB volume or backup before reactivating n8n workflows.
