# Aegis Forecasting & Early Warning Platform: Master Implementation Specification (FINAL)

This document is the complete, self-contained **Master Implementation Specification (FINAL)** for the Aegis Forecasting & Early Warning Platform. It codifies and consolidates the specifications of all 15 frozen and finalized modules. It provides the system architecture, directory structures, consolidated database DDL schemas, feature stores, model registries, governance matrices, n8n workflows, sprint roadmap, production requirements, and readiness checklists. 

In strict compliance with system constraints, all components operate under a **$0/month cost ceiling** across software, data, and development infrastructure, employing open-source technologies (Python, TimescaleDB, n8n, Docker).

---

## 1. System Overview

### 1.1 Complete Architecture Diagram
The Aegis platform utilizes a decoupled, data-driven architecture. Upstream diagnostic engines extract raw features from the Feature Store to generate domain-specific projections. These projections are aggregated exclusively by the Probability Engine to compute system-level probabilities, magnitudes, and early warning scores.

```
       +--------------------------------------------------------------+
       |                  1. Core Data Ingestion Layer                |
       |  (Free APIs: NSE, RBI, FRED, Binance, CoinGecko, DefiLlama)  |
       +------------------------------+-------------------------------+
                                      |
                                      v
       +------------------------------+-------------------------------+
       |                  2. Data & Feature Store Layer               |
       |     (TimescaleDB Hypertables & Feast Local Feature Registry) |
       +------------------------------+-------------------------------+
                                      |
                                      v
       +------------------------------+-------------------------------+
       |               3. Edge Discovery & Validation                 |
       |   (Leading Indicator Discovery Engine, Backtesting Engine,    |
       |            Walk-Forward Validation Engine)                   |
       +------------------------------+-------------------------------+
                                      |
                                      v
       +------------------------------+-------------------------------+
       |                   4. Domain Analytics Engines                |
       |  (Global Liquidity, Liquidity Transmission, Macro Regimes,   |
       |       Breadth & Internal Health, India Sector Stress)        |
       +------------------------------+-------------------------------+
                                      |
                                      v
       +------------------------------+-------------------------------+
       |               5. Central Aggregator & Simulator               |
       |     (Module 8: Probability Engine & Module 10: Scenarios)     |
       |      - Outputs: Probabilities, Magnitudes, and EWS            |
       +------------------------------+-------------------------------+
                                      |
                                      v
       +------------------------------+-------------------------------+
       |             6. Ensemble Governance & Explainability           |
       |  (Ensemble Governance, Forecast Audit, Explainability Engine) |
       +------------------------------+-------------------------------+
                                      |
                                      v
       +------------------------------+-------------------------------+
       |                  7. Alerting & Dashboard Layer               |
       |             (Alerting Webhooks & n8n Workflows)              |
       +--------------------------------------------------------------+
```

### 1.2 Data Flow Diagram
```
[Ingestion Feeds Scrapers]
           |  (Raw Timeseries)
           v
[TimescaleDB Raw Tables] --(Feast Sync)--> [Feast Offline Store]
                                                  |
                                                  v
                                      [Edge Discovery & CPCV Splits]
                                                  |
                                                  v
                                      [Feature store views hydrated]
                                                  |
                                                  v
                                   [Upstream Domain Forecast Engines]
                                                  |  (Regime & Stress Scores)
                                                  v
                                   [Module 8: Probability Engine] 
                                   (Aggregates scores to compute raw probabilities)
                                                  |
                                                  v
                                   [Isotonic / Beta Calibration Layer]
                                                  |  (Physical Probabilities)
                                                  v
                                   [Multi-Horizon Probability Matrix]
                                                  |
                        +-------------------------+-------------------------+
                        |                                                   |
                        v                                                   v
          [Module 10: Scenario Engine]                        [Module 15: Explainability Engine]
          (Applies adaptive stress shocks)                     (Computes TreeSHAP attributions)
                        |                                                   |
                        v                                                   v
          [Shifted Scenario matrices]                        [Explanation audit trail committed]
                        |                                                   |
                        +-------------------------+-------------------------+
                                                  |
                                                  v
                                    [Module 12: Governance Engine]
                                    (Computes Brier / ECE, updates w_i)
                                                  |
                                                  v
                                    [Module 17: Downstream Alerts & n8n]
```

### 1.3 Module Dependency Graph
```
Module 3 (Ingestion) -> Feast Store -> Module 4 (Discovery Engine)
Module 4 (Discovery Engine) -> Module 5 (Backtesting & CPCV Splits)
Module 5 (Backtesting) -> Module 6 (Liquidity) & Module 7 (Breadth)
Module 6 (Liquidity) & Module 7 (Breadth) -> Module 8 (Probability Aggregator)
Module 8 (Probability Engine) -> Module 9 (Regime Memory) & Module 10 (Scenarios)
Module 9 (Regime Memory) & Module 10 (Scenarios) -> Module 13 (India Sectors) & Module 14 (Crypto)
Module 13 (India Sectors) & Module 14 (Crypto) -> Module 15 (Explainability) & Module 11 (Audit)
Module 11 (Audit) -> Module 12 (Governance Dynamic Weights Optimizer)
```

---

## 2. Repository Structure

Aegis conforms to the following standardized Python package and file layout:

```
aegis-platform/
├── README.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── config/
│   ├── config.yaml                         # Global API endpoints & scheduler configurations
│   ├── fees_config.yaml                    # Indian/crypto transaction fees and slippage matrices
│   ├── thresholds_config.yaml              # Bounded event severity limit mappings
│   └── regime_config.yaml                  # GMM clusters, DTW window, and decay parameters
├── database/
│   ├── README.md
│   ├── db_config.yaml                      # TimescaleDB pool configurations
│   ├── migrations/
│   │   ├── 001_initialize_schema.sql       # Extension, base registries, and events catalog
│   │   ├── 002_create_market_hypertables.sql # Price, volume, and macro hypertables
│   │   ├── 003_create_v2_hypertables.sql   # Cycles, rotations, and stablecoin supply trackers
│   │   ├── 004_create_v3_hypertables.sql   # Governance, transmission, and attributions hypertables
│   │   ├── 005_create_discovery_hypertables.sql # Discovered indicators and lifecycles
│   │   └── 006_create_backtest_hypertables.sql # Backtesting splits and performance scorecards
│   └── tests/
│       ├── test_db_constraints.sql
│       └── test_partition_allocations.sql
├── ingestion/
│   ├── README.md
│   ├── data_quality/
│   │   ├── __init__.py
│   │   ├── quality_inspector.py            # Runs inline missing/outlier/null/drift checks
│   │   └── exception_logger.py
│   └── adapters/
│       ├── __init__.py
│       ├── base_client.py                  # Abstract base client with Source Health Scoring
│       ├── nse_client.py                   # Hardened NSE client (Primary equity/breadth)
│       ├── yfinance_client.py              # Yahoo Finance client (Secondary fallback)
│       ├── rbi_liquidity_client.py         # RBI systemic liquidity, SDF, and credit flow client
│       ├── exchange_flow_client.py         # FII/DII capital flows adapter (NSDL/NSE)
│       ├── binance_expanded_client.py      # Binance price & exchange reserve client
│       ├── coingecko_expanded_client.py    # CoinGecko indices, narratives, and crypto breadth client
│       └── defillama_stablecoin_client.py  # Stablecoin supply, velocities, and growth tracker
├── analytics/
│   ├── __init__.py
│   ├── discovery/                          # Module 4: Leading Indicator Discovery
│   │   ├── __init__.py
│   │   ├── discovery_engine.py             # Granger & Transfer Entropy statistical miners
│   │   └── lifecycle_manager.py            # Feature promotion/demotion state machine
│   ├── validation/                         # Module 5: Backtesting & CPCV Splits
│   │   ├── __init__.py
│   │   ├── splitter.py                     # Expanding, Purged K-Fold, and CPCV splitting
│   │   ├── backtest_engine.py              # Out-of-sample trading simulator with frictions
│   │   └── calibration.py                  # Platt Scaling, Beta Calibration, Isotonic solvers
│   ├── diagnostics/                        # Upstream Domain Engines
│   │   ├── __init__.py
│   │   ├── liquidity_engine.py             # US LP, RBI LP, and transmission velocity solvers
│   │   ├── breadth_engine.py               # Composite LDI, average breadth, and HHI penality calculations
│   │   ├── macro_regime.py                 # Macro expansion/slowdown index models
│   │   ├── sector_intelligence.py          # Module 13: Sector stress, health, and rotation
│   │   └── crypto_intelligence.py          # Module 14: Crypto narrative stress, CVD, and funding
│   ├── synthesis/                          # Module 8 & 10: Aggregation & Scenarios
│   │   ├── __init__.py
│   │   ├── probability_aggregator.py       # Gaussian HMM and XGBoost ensemble predictors
│   │   ├── scenario_engine.py              # Macro stress shock, discovery, and counterfactual solver
│   │   └── regime_memory.py                # DTW & Cosine similarity pattern matcher
│   ├── governance/                         # Module 11 & 12: Audit & Weighting
│   │   ├── __init__.py
│   │   ├── governance_engine.py            # Constrained quadratic dynamic weighting solver
│   │   ├── forecast_auditor.py             # Brier contribution & ECE validation tracker
│   │   └── explainability_engine.py        # TreeSHAP and Forecast-to-Forecast Diff Engine
│   └── tests/
│       ├── test_quality_scenarios.py       # Data Quality and Ingestion Health mock tests
│       ├── test_discovery_runner.py        # Discovery and Granger causality tests
│       ├── test_validation_runner.py       # Backtesting and CPCV splits tests
│       └── test_probability_runner.py      # Aggregation, calibration, and EWS tests
├── n8n/                                    # 8. n8n Workflows directory
│   ├── workflow_1_data_collection.json
│   ├── workflow_2_feature_engineering.json
│   ├── workflow_3_model_training.json
│   ├── workflow_4_probability_generation.json
│   ├── workflow_5_scenario_generation.json
│   ├── workflow_6_reporting.json
│   ├── workflow_7_governance.json
│   └── workflow_8_audit_explainability.json
└── dashboards/                             # 18. Dashboard wireframes & assets
    ├── layouts/
    └── static/
```

---

## 3. Database Design

### 3.1 Consolidated DDL Schema & Table Relationships
This consolidated DDL SQL script initializes all tables, hypertables, partition intervals, and index paths:

```sql
-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- 1. Asset Registry table (Metadata)
CREATE TABLE asset_registry (
    asset_id VARCHAR(50) PRIMARY KEY,
    asset_name VARCHAR(100) NOT NULL,
    asset_class VARCHAR(50) NOT NULL,           -- 'EQUITY_SECTOR', 'CRYPTO', 'FIAT_CURRENCY', 'MACRO_INDEX'
    region VARCHAR(50) NOT NULL,                -- 'INDIA', 'GLOBAL', 'US', 'CRYPTO'
    data_provider VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_asset_lookup ON asset_registry (asset_class, region) WHERE is_active = TRUE;

-- 2. Daily Market Price and Volume Metrics
CREATE TABLE daily_market_metrics (
    timestamp TIMESTAMPTZ NOT NULL,
    asset_id VARCHAR(50) REFERENCES asset_registry(asset_id),
    open_price NUMERIC(24, 8) NOT NULL,
    high_price NUMERIC(24, 8) NOT NULL,
    low_price NUMERIC(24, 8) NOT NULL,
    close_price NUMERIC(24, 8) NOT NULL,
    volume NUMERIC(24, 8) CHECK (volume >= 0.0),
    open_interest NUMERIC(24, 8) CHECK (open_interest >= 0.0),
    realized_volatility_30d NUMERIC(8, 6),
    market_cap NUMERIC(30, 2) CHECK (market_cap >= 0.0)
);
SELECT create_hypertable('daily_market_metrics', 'timestamp', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX idx_market_asset_time ON daily_market_metrics (asset_id, timestamp DESC);

-- 3. Macroeconomic & Liquidity Indicators (Fortnightly & Monthly stats)
CREATE TABLE macro_liquidity_indicators (
    timestamp TIMESTAMPTZ NOT NULL,
    indicator_code VARCHAR(50) NOT NULL,
    value NUMERIC(20, 6) NOT NULL,
    revised BOOLEAN DEFAULT FALSE,
    release_date TIMESTAMPTZ NOT NULL
);
SELECT create_hypertable('macro_liquidity_indicators', 'timestamp', chunk_time_interval => INTERVAL '30 days');
CREATE INDEX idx_indicator_time ON macro_liquidity_indicators (indicator_code, timestamp DESC);

-- 4. Crypto On-Chain Metrics
CREATE TABLE crypto_onchain_metrics (
    timestamp TIMESTAMPTZ NOT NULL,
    asset_id VARCHAR(50) REFERENCES asset_registry(asset_id),
    mvrv_z_score NUMERIC(8, 4),
    nupl NUMERIC(8, 4),
    exchange_reserve_btc NUMERIC(24, 8) CHECK (exchange_reserve_btc >= 0.0),
    stablecoin_inflow_volume NUMERIC(24, 8) CHECK (stablecoin_inflow_volume >= 0.0),
    active_addresses INT CHECK (active_addresses >= 0),
    ssr_ratio NUMERIC(10, 4)
);
SELECT create_hypertable('crypto_onchain_metrics', 'timestamp', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX idx_crypto_time ON crypto_onchain_metrics (asset_id, timestamp DESC);

-- 5. Daily Ingestion Source Health Tracking
CREATE TABLE ingestion_source_health (
    timestamp TIMESTAMPTZ NOT NULL,
    source_name VARCHAR(50) NOT NULL,
    availability_rate NUMERIC(5, 4) NOT NULL,
    freshness_seconds INT NOT NULL,
    missing_value_ratio NUMERIC(5, 4) NOT NULL,
    average_latency_ms INT NOT NULL,
    validation_success_rate NUMERIC(5, 4) NOT NULL,
    source_health_score NUMERIC(5, 2) NOT NULL,
    PRIMARY KEY (timestamp, source_name)
);
SELECT create_hypertable('ingestion_source_health', 'timestamp', chunk_time_interval => INTERVAL '30 days');
CREATE INDEX idx_source_health_history ON ingestion_source_health (source_name, timestamp DESC);

-- 6. India Liquidity & Capital Flows Metrics
CREATE TABLE india_liquidity_flows (
    timestamp TIMESTAMPTZ NOT NULL,
    rbi_total_assets NUMERIC(24, 2),
    net_laf_absorption NUMERIC(24, 2),
    marginal_standing_facility NUMERIC(24, 2),
    standing_deposit_facility NUMERIC(24, 2),
    bank_credit_growth_yoy NUMERIC(6, 4) NOT NULL,
    bank_deposit_growth_yoy NUMERIC(6, 4) NOT NULL,
    fii_net_flow_usd NUMERIC(20, 2),
    dii_net_flow_inr NUMERIC(24, 2)
);
SELECT create_hypertable('india_liquidity_flows', 'timestamp', chunk_time_interval => INTERVAL '30 days');
CREATE INDEX idx_in_liquidity ON india_liquidity_flows (timestamp DESC);

-- 7. Expanded Crypto Markets and Narrative Baskets
CREATE TABLE crypto_market_metrics_v2 (
    timestamp TIMESTAMPTZ NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    market_cap NUMERIC(30, 2) NOT NULL,
    close_price NUMERIC(24, 8) NOT NULL,
    volume_24h NUMERIC(30, 2) NOT NULL
);
SELECT create_hypertable('crypto_market_metrics_v2', 'timestamp', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX idx_crypto_v2_lookup ON crypto_market_metrics_v2 (ticker, timestamp DESC);

-- 8. Upgraded Stablecoin Liquidity Engine Trackers
CREATE TABLE stablecoin_liquidity_growth (
    timestamp TIMESTAMPTZ NOT NULL,
    token_symbol VARCHAR(15) NOT NULL,
    circulating_supply NUMERIC(24, 4) NOT NULL,
    daily_growth_pct NUMERIC(8, 6) NOT NULL,
    weekly_growth_pct NUMERIC(8, 6) NOT NULL,
    monthly_growth_pct NUMERIC(8, 6) NOT NULL
);
SELECT create_hypertable('stablecoin_liquidity_growth', 'timestamp', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX idx_stablecoin_lookup ON stablecoin_liquidity_growth (token_symbol, timestamp DESC);

-- 9. Centralized Data Quality Exceptions Tracker
CREATE TABLE data_quality_exceptions (
    timestamp TIMESTAMPTZ NOT NULL,
    source_name VARCHAR(50) NOT NULL,
    field_name VARCHAR(100) NOT NULL,
    exception_type VARCHAR(50) NOT NULL,
    bad_value_raw TEXT,
    severity VARCHAR(20) NOT NULL
);
SELECT create_hypertable('data_quality_exceptions', 'timestamp', chunk_time_interval => INTERVAL '30 days');
CREATE INDEX idx_quality_exceptions ON data_quality_exceptions (source_name, exception_type, timestamp DESC);

-- 10. Dynamic Feature Lifecycle Registry
CREATE TYPE feature_lifecycle_state AS ENUM ('PROPOSED', 'WATCH', 'PROMOTED', 'DEMOTED', 'RETIRED');
CREATE TABLE feature_lifecycle_registry (
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
    retirement_reason TEXT
);
CREATE INDEX idx_feature_state_v3 ON feature_lifecycle_registry (current_state, target_scope);

-- 11. Consolidated Forecasts & Multi-Horizon Probability Matrix
CREATE TYPE probability_risk_regime AS ENUM ('LOW_RISK', 'WATCH', 'ELEVATED', 'HIGH_RISK', 'CRISIS');
CREATE TABLE probability_matrix_outputs_v3 (
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
    current_regime probability_risk_regime NOT NULL
);
SELECT create_hypertable('probability_matrix_outputs_v3', 'timestamp', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX idx_prob_matrix_v3 ON probability_matrix_outputs_v3 (target_scope, current_regime, timestamp DESC);
```

### 3.2 Dynamic Retention and Compression Policies
To ensure low database hardware footprint under the free developmental model:
* **TimescaleDB Compression Policy**: Enable native compression on hypertables (`daily_market_metrics`, `macro_liquidity_indicators`, `crypto_onchain_metrics`, `stablecoin_liquidity_growth`) for chunks older than **90 days**.
* **Pruning and Data Retention**:
  - Ingestion telemetry (`ingestion_job_logs` and `data_quality_exceptions`) older than **180 days** is programmatically pruned weekly.
  - Raw high-frequency market prices older than **730 days (2 years)** are aggregated into weekly averages, and raw daily rows are pruned to conserve disk sectors.

---

## 4. Data Source Catalog

Aegis strictly utilizes the following free and open-source data targets:

| Data Scope | Source Platform | Endpoint / Extraction Target | Frequency | Target Table | Validation Rules |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **India Equities** | NSE India | Bhavcopy CSV direct download: `https://www.nseindia.com/api/allIndices` | Daily (19:30 IST) | `daily_market_metrics` | Close price > 0, Volume $\ge$ 0, 1-day variance limit $\le 30\%$ |
| **India Liquidity** | RBI DBIE WSS | Public Table query feeds: `https://dbie.rbi.org.in/` | Daily / Weekly | `india_liquidity_flows` | Non-negative values for SDF/MSF parameters, repo rate bounds [3.0% to 15.0%] |
| **FII/DII Flows** | NSDL | Daily reports: `https://www.fpi.nsdl.co.in/` | Daily (20:00 IST) | `india_liquidity_flows` | Field check: values must map to numeric USD/INR parameters |
| **Global Macro** | FRED | Series Obs REST API: `https://api.stlouisfed.org/fred/series/observations` | Monthly | `macro_liquidity_indicators` | Reject null characters (convert FRED '.' to NULL), values must be numeric |
| **Crypto Prices** | Binance Public | Candlestick Klines: `https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d` | Hourly | `crypto_market_metrics_v2` | Open/High/Low/Close price must be positive, Volume $\ge 0$ |
| **Market Basket** | CoinGecko Free | Global metrics: `https://api.coingecko.com/api/v3/global` | Daily | `crypto_market_metrics_v2` | Dominate coin ratios must sum to $\le 100\%$ |
| **Stablecoin Supply**| DefiLlama Open | Stablecoin supply timeseries: `https://stablecoins.llama.fi/stablecoincharts/all` | Daily | `stablecoin_liquidity_growth` | Circulating supply must remain strictly positive |

---

## 5. Feature Store Design

Aegis enforces a unified, decentralized feature store registration pipeline utilizing a Feast local repository.

```
       [Raw TimescaleDB hypertables] -> Daily Ingest Run
                     |
                     v
       [Feast Feature Definitions] (feature_store.yaml)
                     |
                     +--> Naming Standard: scope_indicator_derivative
                     +--> e.g. "india_niftybank_rsi_14d"
                     +--> e.g. "crypto_stablecoin_hhi_roc_30d"
                     |
                     v
       [Dynamic In-Memory Registry] (registry.db)
                     |
        +------------+------------+
        |                         |
        v                         v
  [Offline Store]           [Online Store]
  (PostgreSQL/TimescaleDB)  (Redis Cache for scoring)
        |                         |
        +------------+------------+
                     |
                     v
       [Feature Views Retrieval] -> Cron 19:30 IST / 00:30 UTC
```

* **Refresh Schedule**: Feature extraction runs daily immediately following data collection (20:15 IST / 01:15 UTC). Data is read from the offline store, transformed into rolling derivatives, and synced to the online store.

---

## 6. Model Registry Design

To prevent arbitrary model swaps and preserve history, Aegis deploys a structured, versioned Model Registry:

```
================================================================================
MODEL_REGISTRY TABLE (Structural Schema Metadata)
================================================================================
Field Name           | Type       | Description
---------------------+------------+---------------------------------------------
model_hash           | VARCHAR(64)| SHA-256 hash of training parameters & weights
model_type           | VARCHAR(30)| 'GAUSSIAN_HMM', 'XGBOOST', 'QUANTILE_REG'
target_scope         | VARCHAR(50)| Targeted market or sector
model_version        | VARCHAR(20)| Standard SemVer string (e.g., 'v1.4.2')
trained_at           | TIMESTAMPTZ| Calibration completion time
hyperparameters      | JSONB      | Map: {'max_depth': 3, 'learning_rate': 0.01}
active_status        | BOOLEAN    | True if promoted to active inference
================================================================================
```

### Model Promotion & Champion Rules
1. **Dynamic Brier Skill Scoring**: Sub-models are run out-of-sample over a 90-day evaluation window.
2. **Promotion Gate**: A model candidate is promoted to `active_status = TRUE` in the registry and replaces the current champion if and only if:
   $$BSS_{\text{Candidate}} > BSS_{\text{Champion}} + 0.02 \quad \text{strictly}$$
3. **Emergency Demotion Gate**: An active model is instantly demoted to inactive status if its rolling Brier Score decays by $> 25\%$ or the Expected Calibration Error ($ECE$) exceeds $0.20$ over a 14-day window.

---

## 7. Governance Rules

The dynamic governance loop coordinates all model parameters, enforcing strict mathematical boundary rules:

### 7.1 Drift and Retraining Thresholds
- **Feature Drift Warning**: Evaluated daily using the Population Stability Index ($PSI$) over a 30-day window. If $PSI_i \ge 0.10$, a high-priority caution warning is dispatched.
- **Model Retraining Trigger**: If $PSI_i \ge 0.25$ (Critical Drift) OR if the Brier Skill Score ($BSS$) of the active ensemble drops below $0.0$ for 5 consecutive days, the Governance Engine locks predictions, flags the target scope, and triggers an automated walk-forward retraining run.

### 7.2 Dynamic Bounded Weight Optimization
Sub-model weights are solved by minimizing out-of-sample forecast variance (Brier scores) subject to strict inequality constraints:

$$\min_{\mathbf{w}} \mathbf{w}^T \boldsymbol{\Sigma}_{\text{errors}} \mathbf{w}$$

Subject to:
1. $\sum_{i=1}^M w_i = 1.0$ (Fully allocated weights)
2. $w_i \ge 0.0 \quad \forall i$ (No shorting model influence)
3. $w_{\text{Cycle}} \le 0.10$ (Strict boundary constraint capping the Market Cycle Engine weight)

### 7.3 Data Quality Attenuation & Cooldown
- **Attenuation Multiplier**: If any data source Health Score ($HS_i$, from Module 3) drops below 70, its associated model weight is attenuated:
  $$w_{i, \text{attenuated}} = w_i \times \frac{HS_i}{70.0} \quad (\text{if } HS_i \ge 30, \text{ else } 0.0)$$
- **Retraining Cooldown Horizon**: Enforces a strict 30-day cooldown period following any successful model retraining event to prevent over-optimization to short-term regime noise.

---

## 8. n8n Workflow Architecture

Aegis is orchestrated using 8 self-contained n8n workflows. Standard HTTP Request and PostgreSQL nodes are utilized to eliminate premium plugin costs.

```
+---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| n8n WORKFLOW PIPELINE                                                                                                                                                                                                                                                                                                                             |
+---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
| 1. DATA COLLECTION  | -> Cron Trigger -> HTTP node (Free APIs) -> Data Quality Inspector node -> PostgreSQL Insert node -> (On failure: Error Hook to Slack)                                                                                                                                                                                      |
| 2. FEATURE ENG      | -> DB Update Trigger -> Python Execute node (Calculate rolling momentum/diffusion/HHI) -> Feast Online Sync node                                                                                                                                                                                                            |
| 3. MODEL TRAINING   | -> Cron Trigger (Monthly/Drift) -> Python Execution node (Walk-Forward splits & CPCV fitting) -> Model Registry Update node                                                                                                                                                                                                |
| 4. PROB GENERATION  | -> Cron Trigger (Daily 21:00 IST) -> Execute Predictions node (HMM & XGBoost) -> Isotonic Calibration node -> Monotonicity Guard node -> PostgreSQL write                                                                                                                                                                 |
| 5. SCENARIO GEN     | -> Prediction DB Trigger -> Apply Shocks node (standard deviations) -> Run inference through Module 8 node -> Output scenario probabilities                                                                                                                                                                               |
| 6. REPORTING        | -> Scenario Complete Trigger -> Fetch attributions & matched historical analogs -> Compile HTML/Markdown template -> Dispatch E-mail & webhook alerts                                                                                                                                                                     |
| 7. GOVERNANCE       | -> Daily complete trigger -> Fetch rolling Brier scores -> Scipy Optimize constrained solver -> Update DB weight maps -> (PSI Trigger Retraining if drift detected)                                                                                                                                                        |
| 8. AUDIT & EXPLAIN  | -> Trigger daily at realization target -> Fetch outcome labels -> Compute Brier/ECE -> Shapley TreeSHAP attribution node -> Forecast Diff calculation -> Log explainability matrix                                                                                                                                        |
+---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
```

---

## 9. Build Order

Aegis must be developed in a strictly **edge-first** sequence to validate predictive edge before full system overhead is introduced:

```
[Phase 1: Database Setup]
           |
           v
[Phase 2: Ingestion adapters]
           |
           v
[Phase 3: Feature Store Registry]
           |
           v
[Phase 4: Models & CPCV splits] ---------> [Milestone 1: Validate Out-of-Sample Edge]
           |
           v
[Phase 5: Probability Engine Aggregator]
           |
           v
[Phase 6: Sector & Narrative Engines]
           |
           v
[Phase 7: Governance Dynamics & Weights]
           |
           v
[Phase 8: Explainability Attributions]
           |
           v
[Phase 9: Production n8n Orchestration]
```

---

## 10. Codex Execution Plan

### Sprint 1: Datastore & Hardened Ingestion (Weeks 1 - 2)
- **Deliverables**: TimescaleDB hypertables, schema migrations (001-006 SQL), free adapters (NSE, RBI, FRED, Binance, CG, DefiLlama), inline Data Quality layer.
- **Dependencies**: Verified PostgreSQL database cluster connection.
- **Acceptance Criteria**: Passing Ingestion Test Suite 1 with zero Null entries, and Ingestion health scores exceeding 90.

### Sprint 2: Feature Store & Validation splits (Weeks 3 - 4)
- **Deliverables**: Feast feature registry, expanding/rolling split generators, Purged & Embargoed K-Fold validators, CPCV solvers.
- **Dependencies**: Sprint 1 database hydration completed.
- **Acceptance Criteria**: Pass test scenarios checking that no lookahead overlap exists between training and testing split intervals.

### Sprint 3: Core Ensemble & Calibrations (Weeks 5 - 6)
- **Deliverables**: Gaussian emission HMM, XGBoost classifiers, Platt scaling, Beta calibration, Isotonic column regression, and the Multi-Horizon Probability Matrix.
- **Dependencies**: Sprint 2 Feast feature matrices.
- **Acceptance Criteria**: Brier scores under out-of-sample backtests $\le 0.18$ strictly across all 5 horizons.

### Sprint 4: Domain Analytics & Sectors/Narratives (Weeks 7 - 8)
- **Deliverables**: Global Liquidity, Sector Stress, Narrative Rotation PageRank network solvers, expected magnitude quantile models.
- **Dependencies**: Sprint 3 probability matrix aggregators.
- **Acceptance Criteria**: Calculated sector health/stress and crypto narrative scores map strictly inside $[0, 100]$.

### Sprint 5: Scenarios & Analogs (Weeks 9 - 10)
- **Deliverables**: Scenario shock applicator (Base, Bull, Bear, Tail, Liquidity, Sectors, Crypto Crisis), GMM soft-clustering, DTW similarity context matchers, and Counterfactual optimization solver.
- **Dependencies**: Sprint 4 domain feature sets.
- **Acceptance Criteria**: Markov transition matrices sum to 1.0. Counterfactual solver returns top 5 diverse paths under constraint matrices.

### Sprint 6: Governance, Explainability & n8n Deploy (Weeks 11 - 12)
- **Deliverables**: Constrained quadratic dynamic weighting solver (10% Cycle cap constraint), TreeSHAP explainer, Forecast-to-Forecast Diff Engine, n8n JSON workflows deployment, and automated alerts dispatchers.
- **Dependencies**: Sprint 5 analytics metrics.
- **Acceptance Criteria**: Complete end-to-end dry-run executions passing all readiness checklist items.

---

## 11. Production Requirements

The Aegis system strictly conforms to the following operational parameters:

1. **Licensing and Data Sourcing Cost**:
   - Zero software licensing fees: The stack is built entirely using open-source Python packages, PostgreSQL/TimescaleDB, and n8n Community Edition.
   - Zero paid data feeds: All ingestion adapters connect exclusively to free public endpoints or open library wrappers.
2. **System Portability**:
   - Dockerized environments: The database, n8n instance, and Python analytics engines run as independent containerized nodes orchestrated via `docker-compose.yml`.
   - OS Portability: Fully compatible with Linux (Ubuntu/Debian) production servers and local Windows development environments.

---

## 12. Final Readiness Checklist

Developers must verify that the platform satisfies the following parameters before flagging the build as production-ready:

```
================================================================================
AEGIS PRODUCTION READINESS CHECKLIST
================================================================================
[ ] Database hypertables are initialized with 7-day and 30-day chunk partitions.
[ ] Ingestion client fallbacks handle primary NSE API drops.
[ ] Data Quality Layer intercepts and logs outlier prices (Z > 3.5).
[ ] Source Health Score updates daily and downweights degraded feeds (HS < 70).
[ ] Granger Causality F-test rejects non-causal features at p < 0.05.
[ ] Feast offline features sync to online Redis cache with latency < 50ms.
[ ] Backtest split generator enforces a minimum 60-day post-test set embargo.
[ ] CPCV path generator output paths conserve non-overlapping path structures.
[ ] Platt and Beta calibration curves map output probabilities strictly inside [0.0, 1.0].
[ ] Monotonicity check corrects horizon violations using the PAVA solver.
[ ] GMM sector cluster soft weights sum strictly to 1.0.
[ ] Mahalanobis novelty score flags extreme multivariate outliers (SNS > 90.0).
[ ] Expected magnitude quantile regressor respects ordering (5% <= 50% <= 95%).
[ ] Governance Optimizer restricts Market Cycle Engine weight to <= 10.0% strictly.
[ ] Automated retraining trigger launches walk-forward runs when PSI >= 0.25.
[ ] Explainability Engine verifies SHAP additive score conservation (error < 1e-5).
[ ] Forecast-to-Forecast Diff Engine isolates and logs daily primary driver shifts.
[ ] n8n daily execution completes successfully under simulated network dropouts.
================================================================================
```
