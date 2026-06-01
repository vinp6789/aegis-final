# CODEX EXECUTION PLAYBOOK (FINAL)

This playbook translates the frozen **MASTER_IMPLEMENTATION_SPEC_FINAL** into a highly structured, token-efficient, and anti-drift execution sequence. It divides the implementation of the Aegis Forecasting & Early Warning Platform into **18 buildable, testable, and discrete phases**.

---

## 1. Master Codex System Prompt

Re-inject this system prompt at the start of every single execution session:

```
You are Codex, an elite quantitative systems developer. Your objective is to implement the Aegis Forecasting & Early Warning Platform.

CRITICAL INSTRUCTIONS:
1. STRICT BUDGET LIMITS: The system must run under a strict $0/month software, data, and infrastructure cost profile. You must use only open-source Python libraries (Pandas, NumPy, Scikit-Learn, SciPy, Statsmodels, Feast, Psycopg2, and FastAPI/Flask for lightweight dashboarding) and free public data endpoints. Never import or use paid APIs (such as Bloomberg, Glassnode, or premium OpenAI APIs).
2. STICK TO ARCHITECTURE: You must not redesign any system components, alter the database migrations, change the schema, or modify workflows without explicit instruction. 
3. MONOTONICITY & BOUNDARY CHECKS: Ensure risk probabilities are strictly within [0.0, 1.0]. Causal thresholds (p-values) must align with statistical requirements (p < 0.05).
4. REUSE LOGIC: Leverage existing configuration files (config.yaml, fees_config.yaml, thresholds_config.yaml, regime_config.yaml) rather than hardcoding thresholds.
5. NO CODE SKEW: Keep implementation files focused. Write type-annotated, modular, and fully tested code. Implement matching unit and integration test blocks alongside the core code.
```

---

## 2. Anti-Drift Rules

These rules prevent architectural regression and maintain design consistency across development cycles:

*   **Rule 1: Schema Freeze**: No modifying the base TimescaleDB table structure. All modifications must be restricted to SQL migrations designated for that phase.
*   **Rule 2: Weight Ceiling constraint**: The Market Cycle Engine weight in the Governance Optimizer *must* be mathematically bounded to a maximum weight of 10% ($\le 0.10$). Do not allow the optimizer to exceed this limit.
*   **Rule 3: Timezone Safety**: All database timestamps must be timezone-aware and stored strictly in UTC.
*   **Rule 4: Ingestion Isolation**: The Ingestion Layer must run independently of downstream engines. The discovery and prediction loops retrieve data exclusively from the Feature Store/TimescaleDB.
*   **Rule 5: No Paid Components**: Zero cloud-specific features or proprietary databases. Everything must be compatible with standard Linux/Docker environments.

---

## 3. Phase Dependency Map

```
                     +---------------------------------------+
                     |    Phase 1: TimescaleDB Schema        |
                     +-------------------+-------------------+
                                         |
                                         v
                     +-------------------+-------------------+
                     |    Phase 2: Feast Feature Store       |
                     +-------------------+-------------------+
                                         |
                                         v
                     +-------------------+-------------------+
                     |    Phase 3: Ingestion Layer           |
                     +-------------------+-------------------+
                                         |
                                         v
                     +-------------------+-------------------+
                     | Phase 4: Leading Indicator Discovery  |
                     +-------------------+-------------------+
                                         |
                                         v
                     +-------------------+-------------------+
                     |    Phase 5: Backtesting Engine        |
                     +-------------------+-------------------+
                                         |
                                         v
                     +-------------------+-------------------+
                     |    Phase 6: Walk Forward Engine       |
                     +---+-------------------------------+---+
                         |                               |
                         v                               v
           +-------------+-------------+   +-------------+-------------+
           | Phase 7: Liquidity Engine |   |  Phase 8: Breadth Engine  |
           +-------------+-------------+   +-------------+-------------+
                         |                               |
                         +---------------+---------------+
                                         |
                                         v
                     +-------------------+-------------------+
                     |   Phase 9: Probability Engine         |
                     +---+-------------------+---------------+
                         |                   |
                         v                   v
           +-------------+-------------+   +-------------+-------------+
           | Phase 10: Regime Memory   |   | Phase 14: India Sector    |
           +-------------+-------------+   +-------------+-------------+
                         |                               |
                         v                               v
           +-------------+-------------+   +-------------+-------------+
           | Phase 11: Scenario Engine |   | Phase 15: Crypto Engine   |
           +-------------+-------------+   +-------------+-------------+
                         |                               |
                         v                               +-------+
           +-------------+-------------+                         |
           | Phase 12: Forecast Audit  |                         |
           +-------------+-------------+                         v
                         |                 +---------------------+-----+
                         v                 | Phase 16: Explainability  |
           +-------------+-------------+   +---------------------+-----+
           | Phase 13: Governance      |                         |
           +-------------+-------------+                         |
                         |                                       |
                         +---------------+-----------------------+
                                         |
                                         v
                     +-------------------+-------------------+
                     |     Phase 17: Alerting Layer          |
                     +-------------------+-------------------+
                                         |
                                         v
                     +-------------------+-------------------+
                     |     Phase 18: Dashboard               |
                     +---------------------------------------+
```

---

## 4. Phase-by-Phase Execution Plan

---

### PHASE 1: TimescaleDB Schema

*   **Goal**: Establish the base data store, hypertable intervals, indices, and retention policies.
*   **Files to Create**:
    *   `database/migrations/001_initialize_schema.sql`
    *   `database/migrations/002_create_market_hypertables.sql`
    *   `database/migrations/003_create_v2_hypertables.sql`
    *   `database/migrations/004_create_v3_hypertables.sql`
    *   `database/migrations/005_create_discovery_hypertables.sql`
    *   `database/migrations/006_create_backtest_hypertables.sql`
    *   `database/db_config.yaml`
    *   `database/tests/test_db_constraints.sql`
    *   `database/tests/test_partition_allocations.sql`
*   **Files to Modify**: None
*   **Dependencies**: PostgreSQL with TimescaleDB extension enabled.
*   **Unit Tests**: Validate index creation and table definitions in test suite.
*   **Integration Tests**: Run the constraint test scripts on local instance; verify hypertable chunk boundaries.
*   **Acceptance Criteria**: TimescaleDB extension loads successfully. Raw tables partition correctly. Retention and compression policies are active.

#### COPY-PASTE CODEX PROMPT
```
Initialize the Aegis database structure.
Create the configuration at 'database/db_config.yaml' and write the SQL migration files under 'database/migrations/' matching the tables:
- asset_registry (base list)
- daily_market_metrics (7-day hypertable chunk)
- macro_liquidity_indicators (30-day hypertable chunk)
- crypto_onchain_metrics (7-day hypertable chunk)
- ingestion_source_health (30-day hypertable chunk)
- india_liquidity_flows (30-day hypertable chunk)
- crypto_market_metrics_v2 (7-day chunk)
- stablecoin_liquidity_growth (7-day chunk)
- data_quality_exceptions (30-day chunk)
- feature_lifecycle_registry
- probability_matrix_outputs_v3 (7-day chunk)

Set up a native TimescaleDB compression policy to compress chunks older than 90 days for daily_market_metrics, macro_liquidity_indicators, and stablecoin_liquidity_growth.
Write test queries in 'database/tests/test_db_constraints.sql' checking default constraints, non-negative values, and partition validation.
```

*   **STOP CHECKPOINT**: Codex must stop immediately after completing the files.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm `CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE` is present.
    *   [ ] Verify chunk time intervals match the specs (7-day vs 30-day).
    *   [ ] Verify the presence of compression and retention setups.

---

### PHASE 2: Feast Feature Store

*   **Goal**: Initialize the local Feast feature store registry mapping TimescaleDB tables to offline/online views.
*   **Files to Create**:
    *   `aegis-platform/feature_store.yaml`
    *   `aegis-platform/features.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 1.
*   **Unit Tests**: Compile Feast configurations and execute `feast plan`.
*   **Integration Tests**: Test connecting Feast offline queries to TimescaleDB instance.
*   **Acceptance Criteria**: Features compile without error and output a valid offline data frame.

#### COPY-PASTE CODEX PROMPT
```
Set up the Feast Feature Store configuration.
Create 'aegis-platform/feature_store.yaml' using a local SQLite registry (registry.db) and TimescaleDB as the offline store (using psycopg2 connector credentials matching 'database/db_config.yaml').
Create 'aegis-platform/features.py' registering:
- Asset entity ('asset_id')
- Indicator entity ('indicator_code')
- Daily Market Metrics Feature View (open, high, low, close, volume, market_cap)
- Macro Liquidity Indicators Feature View (value, release_date)
- Crypto On-Chain Feature View (mvrv_z_score, ssr_ratio, stablecoin_inflow_volume)

Verify feature definitions run cleanly under 'feast apply'.
```

*   **STOP CHECKPOINT**: Codex must stop immediately after running `feast apply` verification.
*   **REVIEW CHECKLIST**:
    *   [ ] Verify the offline provider maps to postgresql/timescaledb.
    *   [ ] Confirm entity keys (`asset_id`, `indicator_code`) are correctly configured.

---

### PHASE 3: Ingestion Layer

*   **Goal**: Construct the ingestion client network, implementing data quality checking and client fallbacks.
*   **Files to Create**:
    *   `ingestion/data_quality/quality_inspector.py`
    *   `ingestion/data_quality/exception_logger.py`
    *   `ingestion/adapters/base_client.py`
    *   `ingestion/adapters/nse_client.py`
    *   `ingestion/adapters/yfinance_client.py`
    *   `ingestion/adapters/rbi_liquidity_client.py`
    *   `ingestion/adapters/exchange_flow_client.py`
    *   `ingestion/adapters/binance_expanded_client.py`
    *   `ingestion/adapters/coingecko_expanded_client.py`
    *   `ingestion/adapters/defillama_stablecoin_client.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 1, Phase 2.
*   **Unit Tests**: Test the exception logger and quality inspector with invalid raw payloads.
*   **Integration Tests**: Run each ingestion adapter with mock API servers and write data to TimescaleDB.
*   **Acceptance Criteria**: Ingestion logs quality scores. Fallback logic resolves API failures within thresholds.

#### COPY-PASTE CODEX PROMPT
```
Implement the complete Ingestion Layer.
1. Create 'ingestion/data_quality/quality_inspector.py' checking missing inputs, outliers (Z-score > 3.5), and data types. Write anomalies to 'ingestion/data_quality/exception_logger.py'.
2. Create 'ingestion/adapters/base_client.py' specifying properties for:
   - Source availability rate, average latency, and data freshness metrics.
   - Computes dynamic Source Health Score (0-100).
3. Implement Adapters under 'ingestion/adapters/':
   - nse_client.py (Loads official indices, falls back to yfinance_client.py on failure).
   - yfinance_client.py (Secondary equity/macro fallback).
   - rbi_liquidity_client.py (Scrapes SDF, MSF, Net LAF).
   - exchange_flow_client.py (Scrapes NSDL FII/DII daily flows).
   - binance_expanded_client.py (Hourly/daily spot candlestick fetches).
   - coingecko_expanded_client.py (Retrieves narrative market caps).
   - defillama_stablecoin_client.py (Daily stablecoin supplies).

Write unit tests in 'analytics/tests/test_quality_scenarios.py' simulating API dropouts.
```

*   **STOP CHECKPOINT**: Codex must stop after implementing all adapters and verification tests.
*   **REVIEW CHECKLIST**:
    *   [ ] Verify yfinance fallback triggers instantly on NSE client connection errors.
    *   [ ] Confirm raw values are checked for outliers before database inserts.

---

### PHASE 4: Leading Indicator Discovery Engine

*   **Goal**: Programmatically mine and manage causal leading indicators.
*   **Files to Create**:
    *   `analytics/discovery/discovery_engine.py`
    *   `analytics/discovery/lifecycle_manager.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 3.
*   **Unit Tests**: Test causality tests on correlated and uncorrelated synthetic time series.
*   **Integration Tests**: Run discovery against features pulled from the Feast offline store.
*   **Acceptance Criteria**: Granger Causality F-test and Transfer Entropy metrics promotion rules execute cleanly.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 4: Leading Indicator Discovery.
1. Create 'analytics/discovery/discovery_engine.py' utilizing Statsmodels/SciPy to run:
   - Augmented Dickey-Fuller (ADF) stationarity check.
   - Johansen Cointegration test.
   - Granger Causality F-test.
   - Transfer Entropy (using Shannon entropy divergence) to capture non-linear relationships.
2. Create 'analytics/discovery/lifecycle_manager.py' promoting features dynamically into:
   - 'PROPOSED' -> 'WATCH' (Granger p < 0.05 and TE > threshold).
   - 'WATCH' -> 'PROMOTED' (Out-of-sample prediction verification).
   - 'PROMOTED' -> 'DEMOTED' / 'RETIRED' (Performance decays for 3 consecutive months).

Write test suites in 'analytics/tests/test_discovery_runner.py'.
```

*   **STOP CHECKPOINT**: Codex must stop after implementing discovery computations.
*   **REVIEW CHECKLIST**:
    *   [ ] Ensure input data is stationarity-transformed before running Granger Causality.
    *   [ ] Verify the lifecycle transitions update the `feature_lifecycle_registry` table.

---

### PHASE 5: Backtesting Engine

*   **Goal**: Create a reliable, out-of-sample strategy backtester with realistic friction modelling.
*   **Files to Create**:
    *   `analytics/validation/backtest_engine.py`
    *   `config/fees_config.yaml`
*   **Files to Modify**: None
*   **Dependencies**: Phase 4.
*   **Unit Tests**: Run performance calculations (Sharpe, drawdown) on a static returns sequence.
*   **Integration Tests**: Connect backtester to the Feast Offline Store.
*   **Acceptance Criteria**: Outputs performance statistics, deducting transaction costs and slippage according to asset class rules.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 5: Backtesting Engine.
1. Create 'config/fees_config.yaml' containing slippage and transaction costs:
   - India Equity: 0.12% transaction tax + 0.05% slippage.
   - Crypto: 0.10% taker fee + 0.15% slippage.
2. Create 'analytics/validation/backtest_engine.py':
   - Simulates trading decisions.
   - Deducts fees and slippage dynamically based on configuration.
   - Calculates metrics: annualized returns, Sharpe ratio, Sortino ratio, max drawdown, and Brier Score for probability forecasts.
   - Saves results into TimescaleDB backtesting table schemas.
```

*   **STOP CHECKPOINT**: Codex must stop after verifying backtester outputs.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm slippage is subtracted correctly from trade entries and exits.
    *   [ ] Verify metric calculations handle division by zero (e.g., zero volatility).

---

### PHASE 6: Walk Forward Engine

*   **Goal**: Construct cross-validation splitters and dynamic probability calibration algorithms.
*   **Files to Create**:
    *   `analytics/validation/splitter.py`
    *   `analytics/validation/calibration.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 5.
*   **Unit Tests**: Validate cross-validation index splits.
*   **Integration Tests**: Run walk-forward splits on real historical market data.
*   **Acceptance Criteria**: Time-series splits maintain correct training, testing, and embargo buffers.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 5: Cross-Validation & Calibration.
1. Create 'analytics/validation/splitter.py' providing:
   - Rolling/Expanding walk-forward time-series splits.
   - Purged & Embargoed K-Fold splits (with variable embargo windows to prevent leakages).
   - Combinatorial Purged Cross-Validation (CPCV) paths.
2. Create 'analytics/validation/calibration.py' implementing:
   - Platt Scaling wrapper.
   - Isotonic Regression solver.
   - Beta Calibration.
   - Computes Expected Calibration Error (ECE) to choose optimal calibration method.

Write tests in 'analytics/tests/test_validation_runner.py' confirming training/testing intervals never overlap.
```

*   **STOP CHECKPOINT**: Codex must stop after validation tests pass.
*   **REVIEW CHECKLIST**:
    *   [ ] Verify embargo logic shifts test start date by at least 60 days after training boundaries.
    *   [ ] Confirm Platt/Isotonic scaling outputs probabilities bounded to $[0, 1]$.

---

### PHASE 7: Liquidity Engine

*   **Goal**: Calculate global and domestic systemic liquidity indicators and transmission scores.
*   **Files to Create**:
    *   `analytics/diagnostics/liquidity_engine.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 6.
*   **Unit Tests**: Verify liquidity formulas using synthetic input ranges.
*   **Integration Tests**: Read FRED and RBI data from Feast to compute liquidity indices.
*   **Acceptance Criteria**: Liquidity indices update daily without missing values.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 6: Liquidity & Liquidity Transmission Engine.
Create 'analytics/diagnostics/liquidity_engine.py' computing:
1. US Systemic Liquidity: US bank reserves + Fed balance sheet trend - TGA - Reverse Repo.
2. India Systemic Liquidity: RBI SDF + MSF + Net LAF absorption + Bank credit-to-deposit ratio.
3. Liquidity Transmission Score: Speed of transmission of global liquidity changes to Indian indices (rolling correlation of changes).
4. Output values must be normalized to a standard [0, 100] index.
```

*   **STOP CHECKPOINT**: Codex must stop after index verification runs.
*   **REVIEW CHECKLIST**:
    *   [ ] Ensure reverse repo and TGA are correctly subtracted from US systemic liquidity.
    *   [ ] Confirm normalization bounds inputs strictly to $[0, 100]$.

---

### PHASE 8: Breadth Engine

*   **Goal**: Monitor underlying market participation, health metrics, and concentration risks.
*   **Files to Create**:
    *   `analytics/diagnostics/breadth_engine.py`
    *   `analytics/diagnostics/macro_regime.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 6.
*   **Unit Tests**: Test breadth equations on mock index component weights.
*   **Integration Tests**: Query historical index components to calculate daily breadth.
*   **Acceptance Criteria**: Outputs composite Leading Diffusion Index (LDI) and HHI concentration scores.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 7: Breadth & Internal Market Health Engine.
1. Create 'analytics/diagnostics/breadth_engine.py' computing:
   - Percentage of stocks above 50/200 day moving averages.
   - Advance-Decline Line (Cumulative).
   - Herfindahl-Hirschman Index (HHI) for index component market caps (penalizes high concentration).
   - Composite Leading Diffusion Index (LDI).
2. Create 'analytics/diagnostics/macro_regime.py' implementing a GMM classification model to map data to growth/slowdown states.
```

*   **STOP CHECKPOINT**: Codex must stop after saving GMM regime classification outputs.
*   **REVIEW CHECKLIST**:
    *   [ ] Verify the HHI calculation penalizes highly concentrated market structures appropriately.
    *   [ ] Confirm diffusion calculations are bounded within $[-1.0, 1.0]$ or $[0.0, 1.0]$.

---

### PHASE 9: Probability Engine

*   **Goal**: Aggregate upstream analytics into standardized forecast probabilities and early warning scores.
*   **Files to Create**:
    *   `analytics/synthesis/probability_aggregator.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 7, Phase 8.
*   **Unit Tests**: Verify model inputs and probability calculations.
*   **Integration Tests**: Run the model pipeline over historical data to generate the Multi-Horizon Probability Matrix.
*   **Acceptance Criteria**: Probability predictions maintain monotonicity across horizons (PAVA verified).

#### COPY-PASTE CODEX PROMPT
```
Implement Module 8: Probability Engine.
Create 'analytics/synthesis/probability_aggregator.py':
1. Set up an ensemble composed of:
   - Gaussian Emission Hidden Markov Model (HMM) classifying underlying states.
   - XGBoost Classifier predicting event probability.
2. Formulate the Multi-Horizon Probability Matrix (1M, 3M, 6M, 9M, 12M).
3. Apply Isotonic Calibration and use the Pool Adjacent Violators Algorithm (PAVA) to guarantee monotonicity (e.g., probability of event at 6M >= 3M).
4. Calculate composite Early Warning Score (EWS) combining probabilities and momentum indicators.
```

*   **STOP CHECKPOINT**: Codex must stop after completing the aggregator and monotonicity guard.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm PAVA is executed across all probability vectors.
    *   [ ] Verify that the EWS calculates correctly under extreme probability swings.

---

### PHASE 10: Regime Memory Engine

*   **Goal**: Match active market indicators against historical analog sequences using distance measures.
*   **Files to Create**:
    *   `analytics/synthesis/regime_memory.py`
    *   `config/regime_config.yaml`
*   **Files to Modify**: None
*   **Dependencies**: Phase 9.
*   **Unit Tests**: Test Cosine Similarity and DTW calculations.
*   **Integration Tests**: Match current features against the historical TimescaleDB data.
*   **Acceptance Criteria**: Identifies and returns similarity scores for top historical analogs.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 9: Regime Memory Engine.
1. Create 'config/regime_config.yaml' containing search parameters (rolling DTW window = 63 days, decay factor = 0.97).
2. Create 'analytics/synthesis/regime_memory.py' utilizing SciPy:
   - Matches active market features against historical indicators using Dynamic Time Warping (DTW) and Cosine Similarity.
   - Computes similarity index (0-100).
   - Identifies top 3 historical analogs matching the current profile.
```

*   **STOP CHECKPOINT**: Codex must stop after verifying DTW output matrices.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm search algorithms scale well and query database efficiently.
    *   [ ] Verify decay factor discount applies correctly to older analogs.

---

### PHASE 11: Scenario Engine

*   **Goal**: Simulate systemic stress events, mapping transitions, novelty scores, and counterfactual pathways.
*   **Files to Create**:
    *   `analytics/synthesis/scenario_engine.py`
    *   `config/thresholds_config.yaml`
*   **Files to Modify**: None
*   **Dependencies**: Phase 9, Phase 10.
*   **Unit Tests**: Check transition tree probability properties (rows sum to 1.0).
*   **Integration Tests**: Verify scenario runs generate valid target probability matrices.
*   **Acceptance Criteria**: Identifies top 5 counterfactual paths to decrease systemic stress levels.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 10: Scenario Engine.
1. Create 'config/thresholds_config.yaml' storing shock standard deviation bounds.
2. Create 'analytics/synthesis/scenario_engine.py':
   - Applies standard deviation shocks (Mild, Moderate, Severe, Extreme) to inputs.
   - Runs model inferences to generate Base, Bull, Bear, Tail Risk, Liquidity Shock, India Stress, and Crypto Crisis scenarios.
   - Calculates Scenario Novelty Score using Mahalanobis distance.
   - Evaluates transition trees (Markov transition matrix).
   - Generates counterfactual pathways using gradient-free optimizer to output top 5 actions to minimize event risk.
```

*   **STOP CHECKPOINT**: Codex must stop after checking optimizer outputs.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm the Scenario Novelty Score is normalized correctly.
    *   [ ] Check that the counterfactual optimizer yields 5 distinct pathways.

---

### PHASE 12: Forecast Audit Engine

*   **Goal**: Log historical forecasts, audit accuracy, and detect prediction calibration drift.
*   **Files to Create**:
    *   `analytics/governance/forecast_auditor.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 10, Phase 11.
*   **Unit Tests**: Test Brier and calibration calculations.
*   **Integration Tests**: Run the audit loop over historical predictions and target outcomes.
*   **Acceptance Criteria**: Logs accuracy metrics to database; detects calibration drift events.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 11: Forecast Audit Engine.
Create 'analytics/governance/forecast_auditor.py':
1. Tracks prediction records and maps realizations when targets resolve.
2. Calculates:
   - Brier Score & Brier Skill Score (BSS) compared to historical baseline.
   - Expected Calibration Error (ECE).
   - Forecast Drift (monitors shifts in probability distributions over 7D, 30D, and 90D windows).
3. Save results to TimescaleDB.
```

*   **STOP CHECKPOINT**: Codex must stop after database audit writes are validated.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm BSS calculations use the correct historical baseline frequencies.
    *   [ ] Verify the ECE calculation uses appropriate binning configurations.

---

### PHASE 13: Governance Engine

*   **Goal**: Enforce model optimization bounds, drift limits, and execute weight rebalancing.
*   **Files to Create**:
    *   `analytics/governance/governance_engine.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 12.
*   **Unit Tests**: Verify weight optimization boundary rules (specifically the 10% cap).
*   **Integration Tests**: Run optimization loop over historical errors to update ensemble weights.
*   **Acceptance Criteria**: Solves model weight allocations under constraints; handles retraining when thresholds are exceeded.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 12: Governance Engine.
Create 'analytics/governance/governance_engine.py':
1. Monitors drift: tracks Population Stability Index (PSI) daily.
2. Calculates retraining triggers: if PSI >= 0.25, lock outputs and flag retraining state.
3. Formulates the Constrained Weight Optimizer (using SciPy SLSQP solver):
   - Minimizes forecast error variance.
   - Enforce: sum of weights = 1.0, weights >= 0.0.
   - STRICT CONSTRAINT: Cycle Engine weight (w_cycle) <= 0.10 (max 10% influence).
4. Apply health-based attenuation: downweight sub-model weights if corresponding source health scores drop below 70.
5. Prevent retraining loops: enforce 30-day retraining cooldown window.
```

*   **STOP CHECKPOINT**: Codex must stop after verifying the optimization solver.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm `w_cycle <= 0.10` is coded as an inequality constraint in SciPy.
    *   [ ] Verify retraining triggers flag the correct database states.

---

### PHASE 14: India Sector Engine

*   **Goal**: Track, score, and model sector-specific cycles and stress metrics in Indian markets.
*   **Files to Create**:
    *   `analytics/diagnostics/sector_intelligence.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 9.
*   **Unit Tests**: Verify sector health scoring algorithms.
*   **Integration Tests**: Run analysis using macro indicators and capital flow datasets.
*   **Acceptance Criteria**: Calculates scores (health, stress, rotation, drawdown, crash) for 16 sectors.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 13: India Sector Intelligence Engine.
Create 'analytics/diagnostics/sector_intelligence.py':
1. Supports 16 sectors: Banking, NBFC, Realty, Auto, IT, Pharma, Energy, Capital Goods, PSU, FMCG, Metals, Infrastructure, Chemicals, Consumption, Defense, Railways.
2. Calculates sector metrics using Feast features:
   - Sector Health Score, Stress Score, Expansion Score, Rotation Score, expected drawdown, expected upside.
   - Early Warning Score (0-100).
   - Sector Similarity & Novelty scores.
3. Store rolling 30D/90D/180D/360D outcomes.
```

*   **STOP CHECKPOINT**: Codex must stop after validating the sector scoring module.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm all 16 sector keys exist in the configuration mappings.
    *   [ ] Verify drawdown models handle empty historical periods safely.

---

### PHASE 15: Crypto Engine

*   **Goal**: Monitor narrative health, stablecoin supplies, and capital rotations in crypto assets.
*   **Files to Create**:
    *   `analytics/diagnostics/crypto_intelligence.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 9.
*   **Unit Tests**: Validate crypto narrative calculations.
*   **Integration Tests**: Run engine calculations on historical market cap and flow inputs.
*   **Acceptance Criteria**: Outputs narrative health indices, CVD trends, and stablecoin growth rates.

#### COPY-PASTE CODEX PROMPT
```
Implement Module 14: Crypto Intelligence Engine.
Create 'analytics/diagnostics/crypto_intelligence.py':
1. Monitors narratives: BTC, ETH, SOL, BNB, L1, L2, AI, RWA, DeFi, DePIN, Gaming, Memes.
2. Tracks: Coinbase Premium, ETF inflows, exchange inflows, funding rates, open interest, and Cumulative Volume Delta (CVD).
3. Calculates: Narrative Health, Stress, Rotation, Crash/Pump Probability, expected drawdown, expected upside, Early Warning Score.
4. Includes Narrative Similarity and Transition matrices.
```

*   **STOP CHECKPOINT**: Codex must stop after verifying narrative metrics outputs.
*   **REVIEW CHECKLIST**:
    *   [ ] Check that CVD calculations correctly process order book sign changes.
    *   [ ] Verify stablecoin velocity calculations handle zero volume intervals.

---

### PHASE 16: Explainability Engine

*   **Goal**: Generate driver attribution summaries, model explanations, and decision logs.
*   **Files to Create**:
    *   `analytics/governance/explainability_engine.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 14, Phase 15.
*   **Unit Tests**: Verify SHAP additive properties (differences match predictions).
*   **Integration Tests**: Extract attributions for active model prediction runs.
*   **Acceptance Criteria**: Decomposes forecast changes into driver attribution arrays (retaining additive consistency).

#### COPY-PASTE CODEX PROMPT
```
Implement Module 15: Explainability Engine.
Create 'analytics/governance/explainability_engine.py':
1. Integrates TreeSHAP (using shap library) to explain models (HMM states, XGBoost predictions).
2. Computes the Driver Attribution Matrix.
3. Implements the Forecast-to-Forecast Diff Engine, explaining day-over-day changes:
   - Identify top drivers changing predictions from t-1 to t.
4. Generates: Forecast Explanation Reports, analog summaries, and confidence breakdowns.
5. Verifies SHAP additive constraint: sum(attributions) + base_value == prediction_value (error < 1e-5).
```

*   **STOP CHECKPOINT**: Codex must stop after passing SHAP validation tests.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm the SHAP background reference dataset is correctly configured.
    *   [ ] Ensure explanations are formatted cleanly for down-stream rendering.

---

### PHASE 17: Alerting Layer

*   **Goal**: Orchestrate data collection, execution scripts, and alert routing using n8n workflows.
*   **Files to Create**:
    *   `n8n/workflow_1_data_collection.json`
    *   `n8n/workflow_2_feature_engineering.json`
    *   `n8n/workflow_3_model_training.json`
    *   `n8n/workflow_4_probability_generation.json`
    *   `n8n/workflow_5_scenario_generation.json`
    *   `n8n/workflow_6_reporting.json`
    *   `n8n/workflow_7_governance.json`
    *   `n8n/workflow_8_audit_explainability.json`
*   **Files to Modify**: None
*   **Dependencies**: Phase 13, Phase 16.
*   **Unit Tests**: Verify n8n HTTP node triggers and error branches.
*   **Integration Tests**: Run the complete workflow pipeline end-to-end.
*   **Acceptance Criteria**: Executing the workflow pipeline yields updated tables and logs alerts without error.

#### COPY-PASTE CODEX PROMPT
```
Build n8n workflows using standard HTTP/PostgreSQL nodes ($0 premium cost):
1. workflow_1_data_collection.json: Trigger hourly/daily, call adapters, validate, save.
2. workflow_2_feature_engineering.json: Trigger on DB update, run Feast extraction.
3. workflow_3_model_training.json: Retraining triggers (daily checks for drift, monthly runs).
4. workflow_4_probability_generation.json: Daily 21:00 IST calculation.
5. workflow_5_scenario_generation.json: Run scenario engine on updated forecasts.
6. workflow_6_reporting.json: Compile HTML reports and trigger webhook alerts.
7. workflow_7_governance.json: Daily weight updates and drift checks.
8. workflow_8_audit_explainability.json: Compute SHAP values and audit accuracy targets.

Write n8n configuration JSON files using standard node schemas.
```

*   **STOP CHECKPOINT**: Codex must stop after exporting the workflow JSONs.
*   **REVIEW CHECKLIST**:
    *   [ ] Verify the n8n workflows use standard nodes (no premium dependencies).
    *   [ ] Check that retry configurations exist on all data extraction nodes.

---

### PHASE 18: Dashboard

*   **Goal**: Develop the user interface showing platform diagnostics, probability grids, scenarios, and explanations.
*   **Files to Create**:
    *   `dashboards/layouts/main_layout.html`
    *   `dashboards/static/dashboard_style.css`
    *   `dashboards/dashboard_app.py`
*   **Files to Modify**: None
*   **Dependencies**: Phase 17.
*   **Unit Tests**: Test page loads and REST endpoints.
*   **Integration Tests**: Fetch data from database tables and render the active grids.
*   **Acceptance Criteria**: Premium dark mode UI, fully responsive, zero-error dashboard rendering.

#### COPY-PASTE CODEX PROMPT
```
Create a premium-tier dashboard interface.
1. Implement 'dashboards/dashboard_app.py' (using lightweight Flask/FastAPI to serve views).
2. Create 'dashboards/layouts/main_layout.html' using a dark mode aesthetic (Outfit/Inter font, glassmorphic layout, HSL colors).
3. Create 'dashboards/static/dashboard_style.css' for the interface styling.
4. Render UI segments:
   - Multi-Horizon Probability Matrix grid.
   - Systemic early warning scores.
   - Sector/Narrative health maps.
   - Scenario stress shock simulation views.
   - TreeSHAP driver attributions and historical analogs.
   - Ingestion and data source health tracking dashboard.
```

*   **STOP CHECKPOINT**: Codex must stop after completing the dashboard components.
*   **REVIEW CHECKLIST**:
    *   [ ] Confirm styling details reflect the requested premium look.
    *   [ ] Verify the dashboard loads index data with zero lag.
