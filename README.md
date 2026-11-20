# Aegis — Macro Forecasting & Early-Warning Platform

<p align="left">
  <img src="https://img.shields.io/badge/python-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/TimescaleDB-PostgreSQL-4169E1?logo=postgresql&logoColor=white" alt="TimescaleDB"/>
  <img src="https://img.shields.io/badge/orchestration-n8n-EA4B71?logo=n8n&logoColor=white" alt="n8n"/>
  <img src="https://img.shields.io/badge/deploy-Railway-0B0D0E?logo=railway&logoColor=white" alt="Railway"/>
  <img src="https://img.shields.io/badge/tests-23%20test%20modules-success" alt="Tests"/>
  <img src="https://img.shields.io/badge/data-free%20sources%20only-lightgrey" alt="Free data"/>
</p>

A self-hosted forecasting and early-warning system for market regimes. **n8n
workflows** orchestrate the pipeline, a **FastAPI worker** does the heavy
lifting, and **TimescaleDB** stores everything. It runs on free data sources
and has no paid dependencies.

## Architecture

```
 n8n (8 scheduled workflows)
   │  1 data collection   2 feature engineering   3 model training
   │  4 probabilities     5 scenarios             6 reporting
   │  7 governance        8 audit / explainability
   ▼  HTTP POST /run/<stage>
 FastAPI worker (worker_api.py)  ──  GET /health
   │  ingestion + data-quality checks → analytics engines
   │  (liquidity, breadth, regime/HMM, probability, scenarios,
   │   governance, forecast audit, explainability)
   ▼
 TimescaleDB / PostgreSQL  (hypertables, versioned SQL migrations)
```

## DevOps highlights

- **Pipeline orchestration:** 8 exported [n8n workflows](n8n/) call the worker's `/run/*` endpoints on a schedule
- **Infrastructure as code (database):** 7 ordered [SQL migrations](database/migrations/) plus seed data and SQL constraint tests
- **12-factor config:** the database connection comes from `DATABASE_URL`; tuning lives in versioned YAML under [config/](config/)
- **Secrets hygiene:** `.env` files and local state are git-ignored
- **Health and deploy:** `GET /health` reports database connectivity; the [Procfile](Procfile) runs the same `uvicorn` command on Railway or locally
- **Data quality first:** freshness, schema, outlier and quality-score validators run before data reaches the models, and exceptions are logged rather than ignored
- **Documentation:** [architecture status](docs/ARCHITECTURE_STATUS.md), [technical debt register](docs/TECHNICAL_DEBT.md), [deployment readiness report](DEPLOYMENT_READINESS_REPORT.md)

## Repository layout

| Path | Purpose |
|---|---|
| `worker_api.py` | FastAPI app exposing `/health` and the `/run/*` pipeline stages |
| `ingestion/` | Source adapters, persistence and data-quality inspection |
| `analytics/` | Diagnostics, discovery, synthesis, validation and governance engines, plus tests |
| `aegis-platform/` | Feature-store definitions and tests |
| `database/` | Migrations, seeds, DB config and SQL tests |
| `n8n/` | Exported n8n workflow JSON |
| `config/` | Regime, threshold and fee configuration |
| `docs/` | Specs, architecture status and tech-debt notes |

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://user:pass@localhost:5432/aegis
# apply database/migrations/*.sql in order, then:
uvicorn worker_api:app --host 0.0.0.0 --port 8000
curl localhost:8000/health
```

Import the JSON files in `n8n/` into n8n and point their HTTP nodes at the worker URL.

## Tests

```bash
python -m pytest analytics/tests aegis-platform/tests
```

---
*Personal research project. Its outputs are probabilities, not financial advice.*
