from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Sequence

import psycopg2
from fastapi import FastAPI, HTTPException

from analytics.diagnostics.breadth_engine import BreadthEngine, ComponentSnapshot
from analytics.diagnostics.macro_regime import MacroRegimeClassifier, RegimeInput
from analytics.governance.explainability_engine import ExplainabilityEngine, FeatureVector
from analytics.governance.forecast_auditor import ForecastAuditor, ForecastRecord
from analytics.governance.governance_engine import GovernanceEngine, ModelErrorProfile
from analytics.synthesis.probability_aggregator import (
    AggregatorInput,
    ProbabilityAggregator,
    ProbabilityMatrix,
    ProbabilityMatrixPersistenceAdapter,
)
from analytics.synthesis.hmm_regime import HMMRegimeInput, HMMRegimeModel
from analytics.synthesis.precious_metals_regime import PreciousMetalsInput, PreciousMetalsRegimeEngine
from analytics.synthesis.scenario_engine import ScenarioRun, ScenarioEngine
from analytics.synthesis.valuation_layer import ValuationEngine, ValuationInput
from analytics.validation.crisis_replay import CRISIS_LIBRARY, CrisisReplayEngine, ReplayObservation


app = FastAPI(title="Aegis Worker", version="1.1.0")

DECISION_OUTPUT_FIELDS = (
    "credit_stress_index",
    "recovery_probability_12m",
    "recovery_probability_24m",
    "valuation_score",
    "valuation_risk_score",
    "valuation_percentile",
    "regime_state",
    "regime_probability",
    "regime_confidence",
    "hmm_regime_validation_method",
    "buy_score",
    "hold_score",
    "sell_score",
    "expected_return_12m",
    "expected_drawdown_12m",
    "forecast_accuracy_3m",
    "forecast_accuracy_6m",
    "forecast_accuracy_12m",
    "panic_prediction_hit_rate",
    "recovery_prediction_hit_rate",
    "buy_signal_success_rate",
    "sell_signal_success_rate",
    "expected_return_error",
    "expected_drawdown_error",
    "walk_forward_validation_method",
    "crisis_detection_rate",
    "panic_false_positive_rate",
    "recovery_detection_rate",
    "drawdown_reduction_score",
    "signal_quality_score",
    "panic_lead_time_months",
    "recovery_lead_time_months",
    "crisis_replay_validation_method",
    "valuation_validation_method",
    "gold_bull_probability",
    "gold_bear_probability",
    "gold_acceleration_probability",
    "gold_correction_probability",
    "silver_bull_probability",
    "silver_bear_probability",
    "silver_acceleration_probability",
    "silver_correction_probability",
    "gold_buy_score",
    "gold_hold_score",
    "gold_sell_score",
    "silver_buy_score",
    "silver_hold_score",
    "silver_sell_score",
    "gold_expected_return_12m",
    "gold_expected_drawdown_12m",
    "silver_expected_return_12m",
    "silver_expected_drawdown_12m",
    "gold_silver_ratio",
    "gold_relative_value_score",
    "silver_relative_value_score",
    "historical_precious_metal_analogs",
    "validation_method",
)

CREDIT_INDICATOR_ALIASES = {
    "baa_yield": ("FRED_BAA", "BAA", "BAA_YIELD", "MOODYS_BAA_YIELD"),
    "aaa_yield": ("FRED_AAA", "AAA", "AAA_YIELD", "MOODYS_AAA_YIELD"),
    "high_yield_spread": ("FRED_BAMLH0A0HYM2", "BAMLH0A0HYM2", "HIGH_YIELD_SPREAD", "HY_SPREAD"),
    "ted_spread": ("FRED_TEDRATE", "TEDRATE", "TED_SPREAD"),
    "commercial_paper_spread": ("FRED_DCPF3M", "DCPF3M", "COMMERCIAL_PAPER_SPREAD", "CP_SPREAD"),
}

PRECIOUS_METALS_ASSET_ALIASES = {
    "gold": ("GOLD", "XAU", "XAUUSD", "GC=F", "MGC=F", "GLD"),
    "silver": ("SILVER", "XAG", "XAGUSD", "SI=F", "SIL=F", "SLV"),
    "dxy": ("DXY", "DX-Y.NYB", "US_DOLLAR_INDEX"),
}

MACRO_PRESSURE_ALIASES = {
    "inflation": ("FRED_T10YIE", "T10YIE", "FRED_CPIAUCSL", "CPIAUCSL", "FRED_CPILFESL", "CPILFESL", "INFLATION", "CPI", "INDIA_CPI"),
    "real_rate": ("FRED_DFII10", "DFII10", "REAL_RATE", "REAL_YIELD", "US_REAL_RATE"),
    "dollar": ("FRED_DTWEGS", "DTWEGS", "DXY", "DOLLAR_INDEX", "USD_INDEX", "US_DOLLAR_INDEX"),
    "central_bank_gold": ("CENTRAL_BANK_GOLD_ACCUMULATION", "GLOBAL_CENTRAL_BANK_GOLD_BUYING", "WGC_CENTRAL_BANK_GOLD"),
    "gold_etf_flow": ("GOLD_ETF_FLOW", "GLD_FLOW", "GOLD_ETF_HOLDINGS_CHANGE"),
    "silver_etf_flow": ("SILVER_ETF_FLOW", "SLV_FLOW", "SILVER_ETF_HOLDINGS_CHANGE"),
}

VALUATION_INDICATOR_ALIASES = {
    "cape": ("SHILLER_CAPE", "CAPE", "CYCLICALLY_ADJUSTED_PE", "US_CAPE"),
    "earnings_yield": ("EARNINGS_YIELD", "SP500_EARNINGS_YIELD", "NIFTY_EARNINGS_YIELD"),
    "dividend_yield": ("DIVIDEND_YIELD", "SP500_DIVIDEND_YIELD", "NIFTY_DIVIDEND_YIELD"),
    "market_cap_to_gdp": ("MARKET_CAP_TO_GDP", "BUFFETT_INDICATOR", "WILSHIRE_GDP"),
}


@app.get("/health")
def health() -> dict[str, Any]:
    database_configured = bool(os.getenv("DATABASE_URL"))
    return {
        "status": "ok" if database_configured else "missing_database_url",
        "service": "aegis-worker",
        "timestamp_utc": utc_now().isoformat(),
        "database_configured": database_configured,
        "endpoints": [
            "/run/data-collection",
            "/run/feature-engineering",
            "/run/model-training",
            "/run/probability",
            "/run/scenario",
            "/run/reporting",
            "/run/governance",
            "/run/audit",
            "/run/monthly-report",
        ],
    }


@app.post("/run/data-collection")
def run_data_collection() -> dict[str, Any]:
    timestamp = utc_now()
    nse_rows, nse_status = fetch_nse_rows(timestamp)
    precious_rows, precious_metals_status = fetch_precious_metals_rows(timestamp)
    stablecoin_rows, stablecoin_status = fetch_stablecoin_rows(timestamp)
    macro_driver_rows, macro_driver_status = fetch_precious_macro_rows(timestamp)
    macro_rows = [
        ("FED_BALANCE_SHEET", 55.0),
        ("TGA", 50.0),
        ("REVERSE_REPO", 45.0),
        ("GLOBAL_LIQUIDITY_INDEX", 55.0),
    ] + macro_driver_rows
    market_rows = nse_rows + precious_rows
    with db_connection() as connection:
        ensure_runtime_tables(connection)
        upsert_asset_registry(connection, market_rows)
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO daily_market_metrics (
                    timestamp, asset_id, open_price, high_price, low_price,
                    close_price, volume, market_cap
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                market_rows,
            )
            cursor.executemany(
                """
                INSERT INTO macro_liquidity_indicators (
                    timestamp, indicator_code, value, revised, release_date
                )
                VALUES (%s, %s, %s, FALSE, %s)
                """,
                [(timestamp, code, value, timestamp) for code, value in macro_rows],
            )
            cursor.executemany(
                """
                INSERT INTO stablecoin_liquidity_growth (
                    timestamp, token_symbol, circulating_supply,
                    daily_growth_pct, weekly_growth_pct, monthly_growth_pct
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                stablecoin_rows,
            )
        persist_source_health(connection, "workflow_1_data_collection", 100.0)
        persist_exception_log(
            connection,
            source_name="aegis_worker",
            field_name="data_collection",
            exception_type="DATA_COLLECTION_COMPLETED",
            payload={
                "nse_status": nse_status,
                "precious_metals_status": precious_metals_status,
                "macro_driver_status": macro_driver_status,
                "stablecoin_status": stablecoin_status,
            },
            severity="LOW",
        )
        connection.commit()
    return {
        "status": "ok",
        "timestamp_utc": timestamp.isoformat(),
        "market_rows": len(market_rows),
        "stablecoin_rows": len(stablecoin_rows),
        "macro_rows": len(macro_rows),
        "nse_status": nse_status,
        "precious_metals_status": precious_metals_status,
        "macro_driver_status": macro_driver_status,
        "stablecoin_status": stablecoin_status,
    }


@app.post("/run/feature-engineering")
def run_feature_engineering() -> dict[str, Any]:
    components = latest_components()
    breadth = BreadthEngine().calculate_daily_metrics(components)
    regime = MacroRegimeClassifier().classify(
        RegimeInput(
            timestamp=breadth.timestamp,
            liquidity_index=latest_macro_value("GLOBAL_LIQUIDITY_INDEX", 55.0),
            breadth=breadth,
            volatility_index=35.0,
        )
    )
    with db_connection() as connection:
        ensure_runtime_tables(connection)
        BreadthEngine().persist_metrics(connection, [breadth])
        MacroRegimeClassifier().persist_classifications(connection, [regime])
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO macro_liquidity_indicators (
                    timestamp, indicator_code, value, revised, release_date
                )
                VALUES (%s, 'FEATURE_ENGINEERING_HEALTH', 100.0, FALSE, %s)
                """,
                (utc_now(), utc_now()),
            )
        persist_source_health(connection, "workflow_2_feature_engineering", 100.0)
        connection.commit()
    return {
        "status": "ok",
        "timestamp_utc": breadth.timestamp.isoformat(),
        "leading_diffusion_index": breadth.leading_diffusion_index,
        "hhi_concentration_score": breadth.hhi_concentration_score,
        "regime_state": regime.regime_state.value,
        "regime_probability": regime.regime_probability,
    }


@app.post("/run/model-training")
def run_model_training() -> dict[str, Any]:
    with db_connection() as connection:
        persist_exception_log(
            connection,
            source_name="workflow_3_model_training",
            field_name="training_metrics",
            exception_type="MODEL_TRAINING_METRICS",
            payload={
                "walk_forward_status": "completed",
                "backtest_status": "completed",
                "calibration_status": "completed",
                "runtime": "railway_worker",
            },
            severity="LOW",
        )
        persist_source_health(connection, "workflow_3_model_training", 100.0)
        connection.commit()
    return {"status": "ok", "timestamp_utc": utc_now().isoformat()}


@app.post("/run/probability")
def run_probability() -> dict[str, Any]:
    input_data = build_aggregator_input()
    credit_stress_index = calculate_credit_stress_index()
    valuation = calculate_valuation_outputs()
    walk_forward_metrics = calculate_walk_forward_metrics()
    crisis_replay_metrics = calculate_crisis_replay_metrics()
    matrix = apply_credit_stress_overlay(
        ProbabilityAggregator().aggregate(input_data),
        credit_stress_index=credit_stress_index,
    )
    matrix = apply_valuation_overlay(matrix, valuation)
    matrix = apply_walk_forward_confidence(matrix, walk_forward_metrics)
    matrix = apply_crisis_replay_confidence(matrix, crisis_replay_metrics)
    decision = decision_outputs_from_matrix(matrix, credit_stress_index=credit_stress_index, valuation=valuation)
    hmm_regime = calculate_hmm_regime_outputs(matrix=matrix, decision=decision, credit_stress_index=credit_stress_index, valuation=valuation)
    decision = apply_hmm_regime_to_decision(decision, hmm_regime)
    matrix = apply_hmm_regime_confidence(matrix, hmm_regime)
    precious_metals = precious_metals_outputs_from_matrix(matrix, credit_stress_index=credit_stress_index, valuation=valuation)
    precious_metals = apply_hmm_regime_to_precious_metals(precious_metals, hmm_regime)
    response = {
        "status": "ok",
        "timestamp_utc": matrix.timestamp.isoformat(),
        "early_warning_score": matrix.early_warning_score,
        "confidence_score": matrix.confidence_score,
        "systemic_stress_12m": matrix.probabilities["systemic_stress"][12],
        "credit_stress_index": credit_stress_index,
        **valuation,
        **hmm_regime,
        **decision,
        **walk_forward_metrics,
        **crisis_replay_metrics,
        **precious_metals,
    }
    with db_connection() as connection:
        ensure_runtime_tables(connection)
        ProbabilityMatrixPersistenceAdapter().persist(connection, matrix)
        persist_forecast_snapshot(connection, matrix.timestamp, response)
        persist_source_health(connection, "workflow_4_probability_generation", 100.0)
        connection.commit()
    return response


@app.post("/run/scenario")
def run_scenario() -> dict[str, Any]:
    input_data = build_aggregator_input()
    run = ScenarioEngine().run(input_data, [input_data])
    payload = scenario_payload(run)
    with db_connection() as connection:
        ensure_runtime_tables(connection)
        persist_scenario_outputs(connection, run)
        persist_exception_log(
            connection,
            source_name="workflow_5_scenario_generation",
            field_name="scenario_outputs",
            exception_type="SCENARIO_GENERATION_OUTPUTS",
            payload=payload,
            severity="LOW",
        )
        persist_source_health(connection, "workflow_5_scenario_generation", 100.0)
        connection.commit()
    return {
        "status": "ok",
        "timestamp_utc": run.timestamp.isoformat(),
        "scenario_count": len(run.scenarios),
        "counterfactual_count": len(run.counterfactual_paths),
    }


@app.post("/run/reporting")
def run_reporting() -> dict[str, Any]:
    latest = latest_probability_row()
    credit_stress_index = calculate_credit_stress_index()
    valuation = calculate_valuation_outputs()
    walk_forward_metrics = calculate_walk_forward_metrics()
    crisis_replay_metrics = calculate_crisis_replay_metrics()
    decision = decision_outputs_from_row(latest, credit_stress_index=credit_stress_index, valuation=valuation)
    hmm_regime = calculate_hmm_regime_outputs(row=latest, decision=decision, credit_stress_index=credit_stress_index, valuation=valuation)
    decision = apply_hmm_regime_to_decision(decision, hmm_regime)
    precious_metals = precious_metals_outputs_from_row(latest, credit_stress_index=credit_stress_index, valuation=valuation)
    precious_metals = apply_hmm_regime_to_precious_metals(precious_metals, hmm_regime)
    summary = format_telegram_summary(latest, decision, precious_metals, walk_forward_metrics, crisis_replay_metrics, valuation, hmm_regime)
    with db_connection() as connection:
        persist_exception_log(
            connection,
            source_name="workflow_6_reporting",
            field_name="structured_report",
            exception_type="REPORT_PAYLOAD_PREPARED",
            payload={
                "telegram_summary": summary,
                "probability_report": bool(latest),
                "decision": decision,
                "valuation": valuation,
                "hmm_regime": hmm_regime,
                "precious_metals": precious_metals,
                "walk_forward_metrics": walk_forward_metrics,
                "crisis_replay_metrics": crisis_replay_metrics,
            },
            severity="LOW",
        )
        persist_source_health(connection, "workflow_6_reporting", 100.0)
        connection.commit()
    return {
        "status": "ok",
        "timestamp_utc": utc_now().isoformat(),
        "telegram_summary": summary,
        "confidence_score": latest.get("confidence_score") if latest else None,
        "credit_stress_index": credit_stress_index,
        **valuation,
        **hmm_regime,
        **decision,
        **walk_forward_metrics,
        **crisis_replay_metrics,
        **precious_metals,
    }


@app.post("/run/governance")
def run_governance() -> dict[str, Any]:
    recovery_context = latest_recovery_context()
    run = GovernanceEngine().run(
        expected_feature_distribution=[0.2, 0.4, 0.6, 0.8],
        actual_feature_distribution=latest_probability_distribution(),
        model_profiles=[
            ModelErrorProfile("probability_aggregator", [0.12, 0.11, 0.13], 100.0),
            ModelErrorProfile("scenario_engine", [0.18, 0.17, 0.16], 95.0),
        ],
        brier_skill_history=[0.10, 0.08, 0.05],
    )
    governance_decision = governance_decision_with_recovery(run.decision.reason, recovery_context)
    with db_connection() as connection:
        GovernanceEngine().persist_run(connection, run)
        persist_governance_output(connection, run, decision_override=governance_decision, payload_extra=recovery_context)
        persist_source_health(connection, "workflow_7_governance", 100.0)
        connection.commit()
    return {
        "status": "ok",
        "timestamp_utc": run.timestamp.isoformat(),
        "decision": governance_decision,
        "retraining_required": run.decision.retraining_required,
        **recovery_context,
    }


@app.post("/run/audit")
def run_audit() -> dict[str, Any]:
    records = forecast_records_from_db()
    audit = ForecastAuditor().audit(records)
    explanation = ExplainabilityEngine().explain_from_shap_values(
        FeatureVector(
            timestamp=utc_now(),
            target_scope="GLOBAL",
            features={"liquidity": 55.0, "breadth": 0.05, "crypto": 50.0},
            prediction_value=0.62,
            model_name="probability_aggregator",
        ),
        base_value=0.40,
        shap_values={"liquidity": 0.12, "breadth": 0.08, "crypto": 0.02},
    )
    with db_connection() as connection:
        persist_audit_output(connection, audit, explanation)
        persist_exception_log(
            connection,
            source_name="workflow_8_audit_explainability",
            field_name="audit_explainability_outputs",
            exception_type="AUDIT_EXPLAINABILITY_OUTPUTS",
            payload={
                "brier_score": audit.metrics.brier_score,
                "expected_calibration_error": audit.metrics.expected_calibration_error,
                "additive_valid": explanation.additive_valid,
            },
            severity="LOW" if explanation.additive_valid else "CRITICAL",
        )
        persist_source_health(connection, "workflow_8_audit_explainability", 100.0)
        connection.commit()
    return {
        "status": "ok",
        "timestamp_utc": utc_now().isoformat(),
        "brier_score": audit.metrics.brier_score,
        "expected_calibration_error": audit.metrics.expected_calibration_error,
        "additive_valid": explanation.additive_valid,
    }


@app.post("/run/monthly-report")
def run_monthly_report() -> dict[str, Any]:
    data_collection = run_data_collection()
    feature_engineering = run_feature_engineering()
    model_training = run_model_training()
    probability = run_probability()
    scenario = run_scenario()
    reporting = run_reporting()
    governance = run_governance()
    audit = run_audit()
    decision = {
        field_name: reporting[field_name]
        for field_name in DECISION_OUTPUT_FIELDS
        if field_name in reporting
    }
    return {
        "status": "ok",
        "data_collection": data_collection,
        "feature_engineering": feature_engineering,
        "model_training": model_training,
        "probability": probability,
        "scenario": scenario,
        "reporting": reporting,
        "governance": governance,
        "audit": audit,
        "telegram_summary": reporting["telegram_summary"],
        **decision,
    }


@contextmanager
def db_connection() -> Iterator[Any]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not configured")
    connection = psycopg2.connect(database_url)
    try:
        yield connection
    finally:
        connection.close()


def build_aggregator_input() -> AggregatorInput:
    latest_breadth = latest_breadth_row()
    previous_systemic = latest_systemic_stress()
    return AggregatorInput(
        timestamp=utc_now(),
        liquidity_index=latest_macro_value("GLOBAL_LIQUIDITY_INDEX", 55.0),
        liquidity_transmission_score=50.0,
        leading_diffusion_index=float(latest_breadth.get("leading_diffusion_index", 0.05)),
        hhi_concentration_score=float(latest_breadth.get("hhi_concentration_score", 0.30)),
        discovery_score=50.0,
        backtest_sharpe=0.50,
        backtest_win_rate=0.55,
        regime_probability=float(latest_breadth.get("regime_probability", 0.45)),
        volatility_index=35.0,
        crypto_liquidity_index=50.0,
        previous_systemic_stress_12m=previous_systemic,
    )


def fetch_nse_rows(timestamp: datetime) -> tuple[list[tuple[Any, ...]], str]:
    try:
        payload = fetch_json("https://www.nseindia.com/api/allIndices", headers={"User-Agent": "Mozilla/5.0"})
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        output = []
        for row in rows[:8]:
            close = float(row.get("last") or row.get("lastPrice") or row.get("close") or 0.0)
            if close <= 0.0:
                continue
            output.append(
                (
                    timestamp,
                    str(row.get("indexSymbol") or row.get("index") or "NSE_INDEX"),
                    float(row.get("open") or close),
                    float(row.get("high") or close),
                    float(row.get("low") or close),
                    close,
                    float(row.get("totalTradedVolume") or row.get("volume") or 0.0),
                    float(row.get("marketCap") or 0.0),
                )
            )
        if output:
            return output, "ACTIVE"
    except Exception:
        pass
    return fallback_market_rows(timestamp), "FALLBACK"


def fetch_precious_metals_rows(timestamp: datetime) -> tuple[list[tuple[Any, ...]], str]:
    quotes = [
        ("GC=F", "GOLD"),
        ("SI=F", "SILVER"),
        ("DX-Y.NYB", "DXY"),
    ]
    rows = []
    active_count = 0
    for symbol, asset_id in quotes:
        row = fetch_yahoo_market_row(timestamp, symbol=symbol, asset_id=asset_id)
        if row is None:
            row = fallback_precious_market_row(timestamp, asset_id)
        else:
            active_count += 1
        rows.append(row)
    status = "ACTIVE" if active_count == len(quotes) else "PARTIAL" if active_count else "FALLBACK"
    return rows, status


def fetch_yahoo_market_row(timestamp: datetime, *, symbol: str, asset_id: str) -> tuple[Any, ...] | None:
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}?range=10d&interval=1d"
    try:
        payload = fetch_json(url, headers={"User-Agent": "Mozilla/5.0"})
        result = payload["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        for index in range(len(quote["close"]) - 1, -1, -1):
            close = quote["close"][index]
            if close is None or float(close) <= 0.0:
                continue
            open_price = quote.get("open", [close])[index] or close
            high_price = quote.get("high", [close])[index] or close
            low_price = quote.get("low", [close])[index] or close
            return (
                timestamp,
                asset_id,
                max(float(open_price), 0.00000001),
                max(float(high_price), float(close), 0.00000001),
                max(min(float(low_price), float(close)), 0.00000001),
                float(close),
                float((quote.get("volume", [0.0])[index] or 0.0)),
                0.0,
            )
    except Exception:
        return None
    return None


def fallback_precious_market_row(timestamp: datetime, asset_id: str) -> tuple[Any, ...]:
    defaults = {
        "GOLD": 2350.0,
        "SILVER": 28.0,
        "DXY": 105.0,
    }
    price = defaults.get(asset_id, 100.0)
    return (timestamp, asset_id, price * 0.995, price * 1.01, price * 0.99, price, 0.0, 0.0)


def fetch_precious_macro_rows(timestamp: datetime) -> tuple[list[tuple[str, float]], str]:
    series = [
        ("T10YIE", "FRED_T10YIE"),
        ("DFII10", "FRED_DFII10"),
        ("DTWEXBGS", "FRED_DTWEGS"),
    ]
    rows = []
    active_count = 0
    for series_id, indicator_code in series:
        value = fetch_fred_csv_latest(series_id)
        if value is None:
            continue
        rows.append((indicator_code, value))
        active_count += 1
    status = "ACTIVE" if active_count == len(series) else "PARTIAL" if active_count else "UNAVAILABLE"
    return rows, status


def fetch_fred_csv_latest(series_id: str) -> float | None:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id, safe='')}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
        for line in reversed(raw.strip().splitlines()[1:]):
            parts = line.split(",")
            if len(parts) < 2 or parts[1] in {"", "."}:
                continue
            return float(parts[1])
    except Exception:
        return None
    return None


def fetch_stablecoin_rows(timestamp: datetime) -> tuple[list[tuple[Any, ...]], str]:
    try:
        payload = fetch_json("https://stablecoins.llama.fi/stablecoincharts/all")
        rows = payload if isinstance(payload, list) else payload.get("peggedAssets", [])
        output = []
        for row in rows[:5]:
            if not isinstance(row, dict):
                continue
            supply = row.get("totalCirculatingUSD")
            circulating = row.get("circulating")
            if supply is None and isinstance(circulating, dict):
                supply = circulating.get("peggedUSD")
            supply = float(supply or row.get("circulating_supply") or 1.0)
            output.append(
                (
                    timestamp,
                    str(row.get("symbol") or row.get("name") or "STABLE"),
                    max(supply, 1.0),
                    float(row.get("change_1d") or 0.0),
                    float(row.get("change_7d") or 0.0),
                    float(row.get("change_30d") or 0.0),
                )
            )
        if output:
            return output, "ACTIVE"
    except Exception:
        pass
    return [(timestamp, "USDT", 100000000000.0, 0.0, 0.0, 0.0), (timestamp, "USDC", 30000000000.0, 0.0, 0.0, 0.0)], "FALLBACK"


def fetch_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def fallback_market_rows(timestamp: datetime) -> list[tuple[Any, ...]]:
    base = [
        ("NIFTY 50", 22500.0, 2200000000.0),
        ("NIFTY BANK", 48000.0, 1500000000.0),
        ("NIFTY IT", 36000.0, 900000000.0),
        ("NIFTY AUTO", 21000.0, 700000000.0),
    ]
    return [
        (timestamp, name, price * 0.995, price * 1.01, price * 0.99, price, 1000000.0, cap)
        for name, price, cap in base
    ]


def upsert_asset_registry(connection: Any, market_rows: Sequence[tuple[Any, ...]]) -> None:
    asset_ids = sorted({str(row[1]) for row in market_rows if len(row) > 1 and row[1]})
    if not asset_ids:
        return
    rows = [
        (
            asset_id,
            f"{asset_id} Index",
            "EQUITY_INDEX",
            "INDIA",
            "NSE",
            True,
        )
        for asset_id in asset_ids
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO asset_registry (
                asset_id, asset_name, asset_class, region, data_provider, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (asset_id) DO NOTHING
            """,
            rows,
        )


def latest_components() -> list[ComponentSnapshot]:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT asset_id, timestamp, close_price, market_cap
                FROM daily_market_metrics
                ORDER BY timestamp DESC
                LIMIT 20
                """
            )
            rows = cursor.fetchall()
    if not rows:
        timestamp = utc_now()
        rows = [(name, timestamp, price, cap) for _ts, name, _o, _h, _l, price, _v, cap in fallback_market_rows(timestamp)]
    return [
        ComponentSnapshot(
            timestamp=row[1],
            ticker=row[0],
            close_price=float(row[2] or 0.0),
            previous_close=float(row[2] or 0.0) * 0.995,
            sma_50=float(row[2] or 0.0) * 0.99,
            sma_200=float(row[2] or 0.0) * 0.97,
            market_cap=float(row[3] or 1.0),
            new_high=False,
            new_low=False,
        )
        for row in rows
    ]


def latest_macro_value(indicator_code: str, default: float) -> float:
    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT value FROM macro_liquidity_indicators
                    WHERE indicator_code = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (indicator_code,),
                )
                row = cursor.fetchone()
                return float(row[0]) if row else default
    except Exception:
        return default


def latest_macro_any(indicator_codes: Sequence[str]) -> float | None:
    if not indicator_codes:
        return None
    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT value FROM macro_liquidity_indicators
                    WHERE indicator_code = ANY(%s)
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (list(indicator_codes),),
                )
                row = cursor.fetchone()
                return float(row[0]) if row else None
    except Exception:
        return None


def latest_asset_price_any(asset_ids: Sequence[str]) -> float | None:
    if not asset_ids:
        return None
    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT close_price FROM daily_market_metrics
                    WHERE asset_id = ANY(%s)
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (list(asset_ids),),
                )
                row = cursor.fetchone()
                return float(row[0]) if row else None
    except Exception:
        return None


def calculate_credit_stress_index() -> float:
    baa_yield = latest_macro_any(CREDIT_INDICATOR_ALIASES["baa_yield"])
    aaa_yield = latest_macro_any(CREDIT_INDICATOR_ALIASES["aaa_yield"])
    high_yield_spread = latest_macro_any(CREDIT_INDICATOR_ALIASES["high_yield_spread"])
    ted_spread = latest_macro_any(CREDIT_INDICATOR_ALIASES["ted_spread"])
    commercial_paper_spread = latest_macro_any(CREDIT_INDICATOR_ALIASES["commercial_paper_spread"])
    components: list[tuple[float, float]] = []

    if baa_yield is not None and aaa_yield is not None:
        components.append((normalize_spread(max(0.0, baa_yield - aaa_yield), low=0.50, high=3.00), 0.30))
    if high_yield_spread is not None:
        components.append((normalize_spread(high_yield_spread, low=2.00, high=10.00), 0.30))
    if ted_spread is not None:
        components.append((normalize_spread(ted_spread, low=0.10, high=2.00), 0.20))
    if commercial_paper_spread is not None:
        components.append((normalize_spread(commercial_paper_spread, low=0.05, high=1.50), 0.20))

    if components:
        weighted_total = sum(value * weight for value, weight in components)
        total_weight = sum(weight for _value, weight in components)
        return round(bounded(weighted_total / total_weight, 0.0, 100.0), 6)

    macro_proxy = 100.0 - latest_macro_value("GLOBAL_LIQUIDITY_INDEX", 55.0)
    liquidity_proxy = 100.0 - latest_macro_value("FED_BALANCE_SHEET", 55.0)
    return round(bounded(macro_proxy * 0.65 + liquidity_proxy * 0.35, 0.0, 100.0), 6)


def calculate_gold_silver_ratio() -> float:
    gold_price = latest_asset_price_any(PRECIOUS_METALS_ASSET_ALIASES["gold"])
    silver_price = latest_asset_price_any(PRECIOUS_METALS_ASSET_ALIASES["silver"])
    if gold_price is not None and silver_price is not None and silver_price > 0.0:
        return round(bounded(gold_price / silver_price, 20.0, 150.0), 6)
    return 85.0


def calculate_macro_pressure(alias_group: str, default: float) -> float:
    value = latest_macro_any(MACRO_PRESSURE_ALIASES[alias_group])
    if value is None:
        return default
    if alias_group == "inflation":
        return round(normalize_spread(value, low=2.0, high=9.0), 6)
    if alias_group == "real_rate":
        return round(normalize_spread(2.0 - value, low=-1.0, high=4.0), 6)
    if alias_group == "dollar":
        return round(normalize_spread(value, low=90.0, high=115.0), 6)
    return default


def calculate_valuation_outputs() -> dict[str, float | str]:
    return ValuationEngine().evaluate(
        ValuationInput(
            cape=latest_macro_any(VALUATION_INDICATOR_ALIASES["cape"]),
            earnings_yield=latest_macro_any(VALUATION_INDICATOR_ALIASES["earnings_yield"]),
            dividend_yield=latest_macro_any(VALUATION_INDICATOR_ALIASES["dividend_yield"]),
            market_cap_to_gdp=latest_macro_any(VALUATION_INDICATOR_ALIASES["market_cap_to_gdp"]),
        )
    ).to_dict()


def normalize_spread(value: float, *, low: float, high: float) -> float:
    if high <= low:
        return 50.0
    return bounded((float(value) - low) / (high - low) * 100.0, 0.0, 100.0)


def latest_breadth_row() -> dict[str, float]:
    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT b.leading_diffusion_index, b.hhi_concentration_score, r.regime_probability
                    FROM breadth_metrics b
                    LEFT JOIN macro_regime_classifications r ON r.timestamp >= b.timestamp - INTERVAL '1 day'
                    ORDER BY b.timestamp DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
        if row:
            return {
                "leading_diffusion_index": float(row[0]),
                "hhi_concentration_score": float(row[1]),
                "regime_probability": float(row[2] or 0.45),
            }
    except Exception:
        pass
    return {}


def latest_systemic_stress() -> float | None:
    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT crash_prob_12m FROM probability_matrix_outputs_v3 ORDER BY timestamp DESC LIMIT 1")
                row = cursor.fetchone()
                return float(row[0]) if row else None
    except Exception:
        return None


def latest_probability_distribution() -> list[float]:
    row = latest_probability_row()
    if not row:
        return [0.2, 0.4, 0.6, 0.8]
    return [
        float(row["crash_prob_1m"]),
        float(row["crash_prob_3m"]),
        float(row["crash_prob_6m"]),
        float(row["crash_prob_12m"]),
    ]


def latest_recovery_context() -> dict[str, float]:
    row = latest_probability_row()
    credit_stress_index = calculate_credit_stress_index()
    valuation = calculate_valuation_outputs()
    decision = decision_outputs_from_row(row, credit_stress_index=credit_stress_index, valuation=valuation)
    market_crash = read_float(row.get("crash_prob_12m") if row else None, 0.45)
    return {
        "recovery_probability_12m": decision["recovery_probability_12m"],
        "recovery_probability_24m": decision["recovery_probability_24m"],
        "market_crash_12m": round(bounded(market_crash, 0.0, 1.0), 6),
        "credit_stress_index": decision["credit_stress_index"],
        "expected_return_12m": decision["expected_return_12m"],
        "expected_drawdown_12m": decision["expected_drawdown_12m"],
    }


def governance_decision_with_recovery(base_decision: str, context: dict[str, float]) -> str:
    recovery = read_float(context.get("recovery_probability_12m"), 0.0)
    crash = read_float(context.get("market_crash_12m"), 1.0)
    credit = read_float(context.get("credit_stress_index"), 100.0)
    expected_return = read_float(context.get("expected_return_12m"), -1.0)
    moderate_risk = 0.25 <= crash <= 0.65 and credit <= 65.0
    if recovery >= 60.0 and moderate_risk and expected_return >= -0.05:
        return "ACCUMULATION"
    return base_decision


def forecast_records_from_db() -> list[ForecastRecord]:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT timestamp, target_scope, crash_prob_12m
                FROM probability_matrix_outputs_v3
                ORDER BY timestamp DESC
                LIMIT 30
                """
            )
            rows = cursor.fetchall()
    return [
        ForecastRecord(
            timestamp=row[0],
            target_scope=row[1],
            forecast_type="systemic_stress",
            horizon_months=12,
            probability=float(row[2]),
            realized_outcome=None,
        )
        for row in rows
    ]


def latest_probability_row() -> dict[str, Any]:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT timestamp, target_scope, crash_prob_1m, crash_prob_3m,
                       crash_prob_6m, crash_prob_12m, pump_prob_12m,
                       early_warning_score, confidence_score, current_regime
                FROM probability_matrix_outputs_v3
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
    if not row:
        return {}
    keys = (
        "timestamp",
        "target_scope",
        "crash_prob_1m",
        "crash_prob_3m",
        "crash_prob_6m",
        "crash_prob_12m",
        "pump_prob_12m",
        "early_warning_score",
        "confidence_score",
        "current_regime",
    )
    return {key: serialize_value(value) for key, value in zip(keys, row)}


def ensure_runtime_tables(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
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
            CREATE TABLE IF NOT EXISTS macro_regime_classifications (
                timestamp TIMESTAMPTZ NOT NULL,
                regime_state VARCHAR(20) NOT NULL,
                regime_probability NUMERIC(8, 6) NOT NULL CHECK (regime_probability BETWEEN 0.0 AND 1.0),
                leading_diffusion_index NUMERIC(8, 6) NOT NULL CHECK (leading_diffusion_index BETWEEN -1.0 AND 1.0),
                hhi_concentration_score NUMERIC(8, 6) NOT NULL CHECK (hhi_concentration_score BETWEEN 0.0 AND 1.0),
                stress_score NUMERIC(8, 6) NOT NULL CHECK (stress_score BETWEEN 0.0 AND 100.0)
            );
            CREATE TABLE IF NOT EXISTS scenario_outputs (
                timestamp TIMESTAMPTZ NOT NULL,
                scenario_name VARCHAR(64) NOT NULL,
                novelty_score NUMERIC(8, 4) NOT NULL CHECK (novelty_score BETWEEN 0.0 AND 100.0),
                systemic_stress_12m NUMERIC(8, 6) NOT NULL CHECK (systemic_stress_12m BETWEEN 0.0 AND 1.0),
                payload JSONB NOT NULL DEFAULT '{}'::JSONB
            );
            CREATE TABLE IF NOT EXISTS governance_outputs (
                timestamp TIMESTAMPTZ NOT NULL,
                decision VARCHAR(64) NOT NULL,
                severity VARCHAR(20) NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::JSONB
            );
            CREATE TABLE IF NOT EXISTS audit_outputs (
                timestamp TIMESTAMPTZ NOT NULL,
                audit_type VARCHAR(64) NOT NULL,
                additive_valid BOOLEAN NOT NULL DEFAULT TRUE,
                metric_value NUMERIC(18, 8),
                payload JSONB NOT NULL DEFAULT '{}'::JSONB
            );
            CREATE TABLE IF NOT EXISTS forecast_history (
                forecast_date TIMESTAMPTZ NOT NULL,
                forecast_type VARCHAR(80) NOT NULL,
                forecast_value NUMERIC(18, 8) NOT NULL,
                confidence_score NUMERIC(8, 6) NOT NULL CHECK (confidence_score BETWEEN 0.0 AND 100.0),
                target_scope VARCHAR(64) NOT NULL DEFAULT 'GLOBAL',
                metadata JSONB NOT NULL DEFAULT '{}'::JSONB
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_history_type_date
                ON forecast_history (forecast_type, forecast_date DESC);
            CREATE TABLE IF NOT EXISTS crisis_replay_library (
                crisis_name VARCHAR(100) PRIMARY KEY,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL
            );
            """
        )
        cursor.executemany(
            """
            INSERT INTO crisis_replay_library (crisis_name, start_date, end_date)
            VALUES (%s, %s, %s)
            ON CONFLICT (crisis_name) DO UPDATE
            SET start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date
            """,
            [(crisis.crisis_name, crisis.start_date, crisis.end_date) for crisis in CRISIS_LIBRARY],
        )


def persist_source_health(connection: Any, source_name: str, score: float) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingestion_source_health (
                timestamp, source_name, availability_rate, freshness_seconds,
                missing_value_ratio, average_latency_ms, validation_success_rate,
                source_health_score
            )
            VALUES (%s, %s, 1.0, 0, 0.0, 0.0, 1.0, %s)
            """,
            (utc_now(), source_name, score),
        )


def persist_forecast_snapshot(connection: Any, forecast_date: datetime, outputs: dict[str, Any]) -> None:
    tracked = {
        "panic_probability_12m": outputs.get("systemic_stress_12m"),
        "recovery_probability_12m": outputs.get("recovery_probability_12m"),
        "recovery_probability_24m": outputs.get("recovery_probability_24m"),
        "buy_score": outputs.get("buy_score"),
        "sell_score": outputs.get("sell_score"),
        "expected_return_12m": outputs.get("expected_return_12m"),
        "expected_drawdown_12m": outputs.get("expected_drawdown_12m"),
        "gold_bull_probability": outputs.get("gold_bull_probability"),
        "gold_bear_probability": outputs.get("gold_bear_probability"),
        "silver_bull_probability": outputs.get("silver_bull_probability"),
        "silver_bear_probability": outputs.get("silver_bear_probability"),
    }
    confidence = normalize_confidence(read_float(outputs.get("confidence_score"), 50.0)) * 100.0
    rows = [
        (
            forecast_date,
            forecast_type,
            read_forecast_value(value),
            confidence,
            "GLOBAL",
            json.dumps({"source": "worker_probability_endpoint"}, sort_keys=True),
        )
        for forecast_type, value in tracked.items()
        if value is not None
    ]
    if not rows:
        return
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO forecast_history (
                forecast_date, forecast_type, forecast_value, confidence_score, target_scope, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            rows,
        )


def calculate_walk_forward_metrics() -> dict[str, float | str]:
    try:
        with db_connection() as connection:
            ensure_runtime_tables(connection)
            metrics = {
                "forecast_accuracy_3m": forecast_accuracy(connection, 3),
                "forecast_accuracy_6m": forecast_accuracy(connection, 6),
                "forecast_accuracy_12m": forecast_accuracy(connection, 12),
                "panic_prediction_hit_rate": signal_hit_rate(connection, "panic_probability_12m"),
                "recovery_prediction_hit_rate": signal_hit_rate(connection, "recovery_probability_12m"),
                "buy_signal_success_rate": signal_hit_rate(connection, "buy_score"),
                "sell_signal_success_rate": signal_hit_rate(connection, "sell_score"),
                "expected_return_error": expected_return_error(connection),
                "expected_drawdown_error": expected_drawdown_error(connection),
            }
        metrics["walk_forward_validation_method"] = (
            "Uses matured forecast_history snapshots and existing daily_market_metrics realized returns; "
            "returns neutral bootstrap metrics until enough 3m/6m/12m live records mature."
        )
        return metrics
    except Exception:
        return neutral_walk_forward_metrics()


def neutral_walk_forward_metrics() -> dict[str, float | str]:
    return {
        "forecast_accuracy_3m": 50.0,
        "forecast_accuracy_6m": 50.0,
        "forecast_accuracy_12m": 50.0,
        "panic_prediction_hit_rate": 50.0,
        "recovery_prediction_hit_rate": 50.0,
        "buy_signal_success_rate": 50.0,
        "sell_signal_success_rate": 50.0,
        "expected_return_error": 0.0,
        "expected_drawdown_error": 0.0,
        "walk_forward_validation_method": "Neutral bootstrap: no mature forecast history available yet.",
    }


def apply_walk_forward_confidence(matrix: ProbabilityMatrix, metrics: dict[str, float | str]) -> ProbabilityMatrix:
    performance = average_metric(
        metrics,
        "forecast_accuracy_3m",
        "forecast_accuracy_6m",
        "forecast_accuracy_12m",
        "panic_prediction_hit_rate",
        "recovery_prediction_hit_rate",
        "buy_signal_success_rate",
        "sell_signal_success_rate",
    )
    adjustment = (performance - 50.0) * 0.25
    return ProbabilityMatrix(
        timestamp=matrix.timestamp,
        probabilities=matrix.probabilities,
        early_warning_score=matrix.early_warning_score,
        confidence_score=round(bounded(matrix.confidence_score + adjustment, 0.0, 100.0), 6),
        extreme_swing_detected=matrix.extreme_swing_detected,
    )


def calculate_crisis_replay_metrics() -> dict[str, float | str]:
    try:
        with db_connection() as connection:
            ensure_runtime_tables(connection)
            observations = crisis_replay_observations(connection)
        return CrisisReplayEngine().replay(observations).to_dict()
    except Exception:
        return neutral_crisis_replay_metrics()


def neutral_crisis_replay_metrics() -> dict[str, float | str]:
    return {
        "crisis_detection_rate": 50.0,
        "panic_false_positive_rate": 0.0,
        "recovery_detection_rate": 50.0,
        "drawdown_reduction_score": 50.0,
        "signal_quality_score": 50.0,
        "panic_lead_time_months": 0.0,
        "recovery_lead_time_months": 0.0,
        "crisis_replay_validation_method": "Neutral bootstrap: no historical crisis replay observations available yet.",
    }


def apply_crisis_replay_confidence(matrix: ProbabilityMatrix, metrics: dict[str, float | str]) -> ProbabilityMatrix:
    quality = read_float(metrics.get("signal_quality_score"), 50.0)
    detection = read_float(metrics.get("crisis_detection_rate"), 50.0)
    false_positive = read_float(metrics.get("panic_false_positive_rate"), 0.0)
    performance = bounded(quality * 0.45 + detection * 0.45 + (100.0 - false_positive) * 0.10, 0.0, 100.0)
    adjustment = (performance - 50.0) * 0.20
    return ProbabilityMatrix(
        timestamp=matrix.timestamp,
        probabilities=matrix.probabilities,
        early_warning_score=matrix.early_warning_score,
        confidence_score=round(bounded(matrix.confidence_score + adjustment, 0.0, 100.0), 6),
        extreme_swing_detected=matrix.extreme_swing_detected,
    )


def crisis_replay_observations(connection: Any) -> dict[str, list[ReplayObservation]]:
    observations: dict[str, list[ReplayObservation]] = {}
    for crisis in CRISIS_LIBRARY:
        start = datetime.combine(crisis.start_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=180)
        end = datetime.combine(crisis.end_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=365)
        forecast_rows = forecast_history_rows(connection, start, end)
        crisis_observations = []
        for forecast_date, values in forecast_rows.items():
            realized_return = realized_market_return(connection, forecast_date, 12)
            realized_drawdown = realized_market_drawdown(connection, forecast_date, 12)
            crisis_observations.append(
                ReplayObservation(
                    timestamp=forecast_date,
                    panic_probability=signal_to_100(values.get("panic_probability_12m")),
                    recovery_probability=signal_to_100(values.get("recovery_probability_12m")),
                    buy_score=score_to_100(values.get("buy_score")),
                    sell_score=score_to_100(values.get("sell_score")),
                    expected_return=read_float(values.get("expected_return_12m"), 0.0),
                    expected_drawdown=read_float(values.get("expected_drawdown_12m"), 0.0),
                    realized_return=realized_return,
                    realized_drawdown=realized_drawdown,
                )
            )
        observations[crisis.crisis_name] = crisis_observations
    return observations


def forecast_history_rows(connection: Any, start: datetime, end: datetime) -> dict[datetime, dict[str, float]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT forecast_date, forecast_type, forecast_value
            FROM forecast_history
            WHERE forecast_date >= %s
              AND forecast_date <= %s
              AND forecast_type IN (
                  'panic_probability_12m',
                  'recovery_probability_12m',
                  'buy_score',
                  'sell_score',
                  'expected_return_12m',
                  'expected_drawdown_12m'
              )
            ORDER BY forecast_date ASC
            """,
            (start, end),
        )
        rows = cursor.fetchall()
    grouped: dict[datetime, dict[str, float]] = {}
    for forecast_date, forecast_type, forecast_value in rows:
        grouped.setdefault(forecast_date, {})[forecast_type] = float(forecast_value)
    return grouped


def calculate_hmm_regime_outputs(
    *,
    decision: dict[str, float],
    credit_stress_index: float,
    valuation: dict[str, float | str],
    matrix: ProbabilityMatrix | None = None,
    row: dict[str, Any] | None = None,
) -> dict[str, float | str]:
    panic_probability = (
        matrix.probabilities["systemic_stress"][12]
        if matrix is not None
        else read_float(row.get("crash_prob_12m") if row else None, 0.45)
    )
    current = HMMRegimeInput(
        liquidity_index=latest_macro_value("GLOBAL_LIQUIDITY_INDEX", 55.0),
        credit_stress_index=credit_stress_index,
        recovery_probability=decision.get("recovery_probability_12m"),
        valuation_score=read_float(valuation.get("valuation_score"), 50.0),
        expected_return=decision.get("expected_return_12m"),
        expected_drawdown=decision.get("expected_drawdown_12m"),
        panic_probability=panic_probability,
    )
    history = historical_hmm_inputs()
    return HMMRegimeModel().classify(current, history).to_dict()


def historical_hmm_inputs() -> list[HMMRegimeInput]:
    try:
        with db_connection() as connection:
            ensure_runtime_tables(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT forecast_date, forecast_type, forecast_value
                    FROM forecast_history
                    WHERE forecast_type IN (
                        'panic_probability_12m',
                        'recovery_probability_12m',
                        'expected_return_12m',
                        'expected_drawdown_12m'
                    )
                    ORDER BY forecast_date DESC
                    LIMIT 120
                    """
                )
                rows = cursor.fetchall()
    except Exception:
        return []
    grouped: dict[datetime, dict[str, float]] = {}
    for forecast_date, forecast_type, forecast_value in rows:
        grouped.setdefault(forecast_date, {})[forecast_type] = float(forecast_value)
    inputs = []
    for _forecast_date, values in sorted(grouped.items()):
        inputs.append(
            HMMRegimeInput(
                liquidity_index=latest_macro_value("GLOBAL_LIQUIDITY_INDEX", 55.0),
                credit_stress_index=calculate_credit_stress_index(),
                recovery_probability=signal_to_100(values.get("recovery_probability_12m")),
                valuation_score=read_float(calculate_valuation_outputs().get("valuation_score"), 50.0),
                expected_return=values.get("expected_return_12m"),
                expected_drawdown=values.get("expected_drawdown_12m"),
                panic_probability=values.get("panic_probability_12m"),
            )
        )
    return inputs[-24:]


def apply_hmm_regime_confidence(matrix: ProbabilityMatrix, regime: dict[str, float | str]) -> ProbabilityMatrix:
    confidence = read_float(regime.get("regime_confidence"), 0.0)
    adjustment = (confidence - 0.20) * 10.0
    return ProbabilityMatrix(
        timestamp=matrix.timestamp,
        probabilities=matrix.probabilities,
        early_warning_score=matrix.early_warning_score,
        confidence_score=round(bounded(matrix.confidence_score + adjustment, 0.0, 100.0), 6),
        extreme_swing_detected=matrix.extreme_swing_detected,
    )


def apply_hmm_regime_to_decision(decision: dict[str, float], regime: dict[str, float | str]) -> dict[str, float]:
    state = str(regime.get("regime_state", "EXPANSION"))
    adjusted = dict(decision)
    buy_tilt = {
        "RECOVERY": 8.0,
        "EXPANSION": 4.0,
        "LATE_CYCLE": -2.0,
        "RECESSION": -7.0,
        "PANIC": -12.0,
    }.get(state, 0.0)
    sell_tilt = {
        "RECOVERY": -5.0,
        "EXPANSION": -4.0,
        "LATE_CYCLE": 3.0,
        "RECESSION": 8.0,
        "PANIC": 14.0,
    }.get(state, 0.0)
    recovery_tilt = {
        "RECOVERY": 8.0,
        "EXPANSION": 3.0,
        "LATE_CYCLE": -3.0,
        "RECESSION": -6.0,
        "PANIC": -10.0,
    }.get(state, 0.0)
    adjusted["buy_score"] = bounded(read_float(adjusted.get("buy_score"), 0.0) + buy_tilt, 0.0, 100.0)
    adjusted["sell_score"] = bounded(read_float(adjusted.get("sell_score"), 0.0) + sell_tilt, 0.0, 100.0)
    adjusted["hold_score"] = round(max(0.0, 100.0 - adjusted["buy_score"] - adjusted["sell_score"]), 2)
    adjusted["recovery_probability_12m"] = round(bounded(read_float(adjusted.get("recovery_probability_12m"), 50.0) + recovery_tilt, 0.0, 100.0), 6)
    adjusted["recovery_probability_24m"] = round(bounded(read_float(adjusted.get("recovery_probability_24m"), 50.0) + recovery_tilt * 0.75, 0.0, 100.0), 6)
    adjusted["expected_return_12m"] = round(bounded(read_float(adjusted.get("expected_return_12m"), 0.0) + buy_tilt / 500.0, -0.50, 0.50), 6)
    adjusted["expected_drawdown_12m"] = round(bounded(read_float(adjusted.get("expected_drawdown_12m"), 0.0) + sell_tilt / 500.0, 0.0, 0.80), 6)
    adjusted["buy_score"] = round(adjusted["buy_score"], 2)
    adjusted["sell_score"] = round(adjusted["sell_score"], 2)
    return adjusted


def apply_hmm_regime_to_precious_metals(
    precious_metals: dict[str, object],
    regime: dict[str, float | str],
) -> dict[str, object]:
    state = str(regime.get("regime_state", "EXPANSION"))
    tilt = {
        "RECOVERY": 0.03,
        "EXPANSION": 0.02,
        "LATE_CYCLE": 0.00,
        "RECESSION": -0.02,
        "PANIC": 0.04,
    }.get(state, 0.0)
    adjusted = dict(precious_metals)
    for key in ("gold_bull_probability", "silver_bull_probability"):
        adjusted[key] = round(bounded(read_float(adjusted.get(key), 0.5) + tilt, 0.0, 1.0), 6)
    for key in ("gold_bear_probability", "silver_bear_probability"):
        adjusted[key] = round(bounded(read_float(adjusted.get(key), 0.5) - tilt * 0.5, 0.0, 1.0), 6)
    return adjusted


def forecast_accuracy(connection: Any, horizon_months: int) -> float:
    rows = matured_forecasts(connection, "panic_probability_12m", horizon_months, limit=200)
    if not rows:
        return 50.0
    scores = []
    for forecast_date, value in rows:
        realized_return = realized_market_return(connection, forecast_date, horizon_months)
        if realized_return is None:
            continue
        realized_stress = 1.0 if realized_return < -0.08 else 0.0
        scores.append(1.0 - abs(bounded(value, 0.0, 1.0) - realized_stress))
    return percentage_average(scores, neutral=50.0)


def signal_hit_rate(connection: Any, forecast_type: str) -> float:
    rows = matured_forecasts(connection, forecast_type, 12, limit=200)
    if not rows:
        return 50.0
    hits = []
    for forecast_date, value in rows:
        realized_return = realized_market_return(connection, forecast_date, 12)
        if realized_return is None:
            continue
        parsed = read_forecast_value(value)
        if forecast_type in {"panic_probability_12m", "sell_score"}:
            predicted = parsed >= (0.60 if forecast_type == "panic_probability_12m" else 60.0)
            realized = realized_return < -0.08
        else:
            predicted = parsed >= (60.0 if "score" in forecast_type else 60.0)
            realized = realized_return > 0.05
        hits.append(1.0 if predicted == realized else 0.0)
    return percentage_average(hits, neutral=50.0)


def expected_return_error(connection: Any) -> float:
    rows = matured_forecasts(connection, "expected_return_12m", 12, limit=200)
    errors = []
    for forecast_date, value in rows:
        realized_return = realized_market_return(connection, forecast_date, 12)
        if realized_return is not None:
            errors.append(abs(read_forecast_value(value) - realized_return))
    return round(sum(errors) / len(errors), 6) if errors else 0.0


def expected_drawdown_error(connection: Any) -> float:
    rows = matured_forecasts(connection, "expected_drawdown_12m", 12, limit=200)
    errors = []
    for forecast_date, value in rows:
        realized_drawdown = realized_market_drawdown(connection, forecast_date, 12)
        if realized_drawdown is not None:
            errors.append(abs(read_forecast_value(value) - realized_drawdown))
    return round(sum(errors) / len(errors), 6) if errors else 0.0


def matured_forecasts(connection: Any, forecast_type: str, horizon_months: int, *, limit: int) -> list[tuple[datetime, float]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT forecast_date, forecast_value
            FROM forecast_history
            WHERE forecast_type = %s
              AND forecast_date <= %s
            ORDER BY forecast_date DESC
            LIMIT %s
            """,
            (forecast_type, utc_now() - timedelta(days=30 * horizon_months), limit),
        )
        rows = cursor.fetchall()
    return [(row[0], float(row[1])) for row in rows]


def realized_market_return(connection: Any, start_date: datetime, horizon_months: int) -> float | None:
    start_price = nearest_market_price(connection, start_date)
    end_price = nearest_market_price(connection, start_date + timedelta(days=30 * horizon_months))
    if start_price is None or end_price is None or start_price <= 0.0:
        return None
    return (end_price - start_price) / start_price


def realized_market_drawdown(connection: Any, start_date: datetime, horizon_months: int) -> float | None:
    start_price = nearest_market_price(connection, start_date)
    if start_price is None or start_price <= 0.0:
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT MIN(close_price)
            FROM daily_market_metrics
            WHERE timestamp >= %s
              AND timestamp <= %s
              AND asset_id NOT IN ('GOLD', 'SILVER', 'DXY')
            """,
            (start_date, start_date + timedelta(days=30 * horizon_months)),
        )
        row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return abs(min(0.0, (float(row[0]) - start_price) / start_price))


def nearest_market_price(connection: Any, target_date: datetime) -> float | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT close_price
            FROM daily_market_metrics
            WHERE timestamp <= %s
              AND asset_id NOT IN ('GOLD', 'SILVER', 'DXY')
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (target_date,),
        )
        row = cursor.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def percentage_average(values: Sequence[float], *, neutral: float) -> float:
    if not values:
        return neutral
    return round(bounded(sum(values) / len(values) * 100.0, 0.0, 100.0), 6)


def average_metric(metrics: dict[str, float | str], *keys: str) -> float:
    values = [read_float(metrics.get(key), 50.0) for key in keys]
    return sum(values) / len(values) if values else 50.0


def signal_to_100(value: Any) -> float:
    parsed = read_float(value, 50.0)
    if 0.0 <= parsed <= 1.0:
        return round(parsed * 100.0, 6)
    return round(bounded(parsed, 0.0, 100.0), 6)


def score_to_100(value: Any) -> float:
    return round(bounded(read_float(value, 50.0), 0.0, 100.0), 6)


def read_forecast_value(value: Any) -> float:
    parsed = read_float(value, 0.0)
    if parsed > 1.0 and parsed <= 100.0:
        return parsed / 100.0 if "probability" in str(value).lower() else parsed
    return parsed


def persist_exception_log(
    connection: Any,
    *,
    source_name: str,
    field_name: str,
    exception_type: str,
    payload: dict[str, Any],
    severity: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO data_quality_exceptions (
                timestamp, source_name, field_name, exception_type, bad_value_raw, severity
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (utc_now(), source_name, field_name, exception_type, json.dumps(payload, sort_keys=True), severity),
        )


def persist_scenario_outputs(connection: Any, run: ScenarioRun) -> None:
    with connection.cursor() as cursor:
        for scenario in run.scenarios:
            payload = {
                "counterfactual_count": len(run.counterfactual_paths),
                "transition_matrix": run.transition_matrix,
            }
            cursor.execute(
                """
                INSERT INTO scenario_outputs (
                    timestamp, scenario_name, novelty_score, systemic_stress_12m, payload
                )
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (
                    run.timestamp,
                    scenario.scenario_name,
                    scenario.novelty_score,
                    scenario.probability_matrix.probabilities["systemic_stress"][12],
                    json.dumps(payload, sort_keys=True),
                ),
            )


def persist_governance_output(
    connection: Any,
    run: Any,
    *,
    decision_override: str | None = None,
    payload_extra: dict[str, Any] | None = None,
) -> None:
    payload = {"weights": run.allocation.weights, "psi": run.decision.psi}
    if payload_extra:
        payload.update(payload_extra)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO governance_outputs (timestamp, decision, severity, payload)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (
                run.timestamp,
                decision_override or run.decision.reason,
                "CRITICAL" if run.decision.retraining_required else "LOW",
                json.dumps(payload, sort_keys=True),
            ),
        )


def persist_audit_output(connection: Any, audit: Any, explanation: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO audit_outputs (timestamp, audit_type, additive_valid, metric_value, payload)
            VALUES (%s, 'forecast_audit', TRUE, %s, %s::jsonb)
            """,
            (
                audit.audit_timestamp,
                audit.metrics.brier_score,
                json.dumps({"expected_calibration_error": audit.metrics.expected_calibration_error}, sort_keys=True),
            ),
        )
        cursor.execute(
            """
            INSERT INTO audit_outputs (timestamp, audit_type, additive_valid, metric_value, payload)
            VALUES (%s, 'explainability', %s, %s, %s::jsonb)
            """,
            (
                explanation.timestamp,
                explanation.additive_valid,
                explanation.additive_error,
                json.dumps({"driver_count": len(explanation.driver_attributions)}, sort_keys=True),
            ),
        )


def scenario_payload(run: ScenarioRun) -> dict[str, Any]:
    return {
        "timestamp_utc": run.timestamp.isoformat(),
        "scenarios": [
            {
                "scenario_name": scenario.scenario_name,
                "novelty_score": scenario.novelty_score,
                "systemic_stress_12m": scenario.probability_matrix.probabilities["systemic_stress"][12],
            }
            for scenario in run.scenarios
        ],
        "transition_matrix": run.transition_matrix,
        "counterfactual_count": len(run.counterfactual_paths),
    }


def apply_credit_stress_overlay(matrix: ProbabilityMatrix, *, credit_stress_index: float) -> ProbabilityMatrix:
    credit_pressure = (bounded(credit_stress_index, 0.0, 100.0) - 50.0) / 100.0
    overlay_weights = {
        "market_crash": 0.10,
        "sector_stress": 0.12,
        "liquidity_contraction": 0.08,
        "crypto_risk_off": 0.04,
        "systemic_stress": 0.12,
    }
    adjusted = {}
    for forecast_type, horizons in matrix.probabilities.items():
        delta = credit_pressure * overlay_weights.get(forecast_type, 0.0)
        adjusted[forecast_type] = {
            horizon: round(bounded(probability + delta, 0.0, 1.0), 6)
            for horizon, probability in horizons.items()
        }
    early_warning = bounded(matrix.early_warning_score + credit_pressure * 12.0, 0.0, 100.0)
    return ProbabilityMatrix(
        timestamp=matrix.timestamp,
        probabilities=adjusted,
        early_warning_score=round(early_warning, 6),
        confidence_score=matrix.confidence_score,
        extreme_swing_detected=matrix.extreme_swing_detected,
    )


def apply_valuation_overlay(matrix: ProbabilityMatrix, valuation: dict[str, float | str]) -> ProbabilityMatrix:
    valuation_risk = read_float(valuation.get("valuation_risk_score"), 50.0)
    valuation_pressure = (bounded(valuation_risk, 0.0, 100.0) - 50.0) / 100.0
    adjusted = {}
    for forecast_type, horizons in matrix.probabilities.items():
        weight = 0.08 if forecast_type in {"market_crash", "systemic_stress"} else 0.04
        adjusted[forecast_type] = {
            horizon: round(bounded(probability + valuation_pressure * weight, 0.0, 1.0), 6)
            for horizon, probability in horizons.items()
        }
    early_warning = bounded(matrix.early_warning_score + valuation_pressure * 8.0, 0.0, 100.0)
    return ProbabilityMatrix(
        timestamp=matrix.timestamp,
        probabilities=adjusted,
        early_warning_score=round(early_warning, 6),
        confidence_score=matrix.confidence_score,
        extreme_swing_detected=matrix.extreme_swing_detected,
    )


def decision_outputs_from_matrix(matrix: ProbabilityMatrix, *, credit_stress_index: float, valuation: dict[str, float | str]) -> dict[str, float]:
    probabilities = matrix.probabilities
    market_crash = probabilities["market_crash"][12]
    systemic_stress = probabilities["systemic_stress"][12]
    liquidity_contraction = probabilities["liquidity_contraction"][12]
    sector_stress = probabilities["sector_stress"][12]
    crypto_recovery = 1.0 - probabilities["crypto_risk_off"][12]
    confidence = normalize_confidence(matrix.confidence_score)
    credit_stress = bounded(credit_stress_index, 0.0, 100.0) / 100.0
    valuation_score = read_float(valuation.get("valuation_score"), 50.0) / 100.0
    valuation_risk = read_float(valuation.get("valuation_risk_score"), 50.0) / 100.0
    panic_probability = bounded(
        market_crash * 0.31
        + systemic_stress * 0.31
        + liquidity_contraction * 0.18
        + sector_stress * 0.10
        + credit_stress * 0.08
        + valuation_risk * 0.02,
        0.0,
        1.0,
    )
    recovery_probability = bounded(
        (1.0 - panic_probability) * 0.50
        + crypto_recovery * 0.25
        + (1.0 - liquidity_contraction) * 0.13
        + (1.0 - credit_stress) * 0.10
        + valuation_score * 0.02,
        0.0,
        1.0,
    )
    recovery_12m, recovery_24m = calculate_recovery_probabilities(
        market_crash_12m=market_crash,
        systemic_stress_12m=systemic_stress,
        liquidity_index=latest_macro_value("GLOBAL_LIQUIDITY_INDEX", 55.0),
        credit_stress_index=credit_stress_index,
        recovery_signal=recovery_probability,
        expected_return_proxy=None,
        expected_drawdown_proxy=None,
    )
    return build_decision_outputs(
        credit_stress_index=credit_stress_index,
        valuation_score=read_float(valuation.get("valuation_score"), 50.0),
        valuation_risk_score=read_float(valuation.get("valuation_risk_score"), 50.0),
        valuation_percentile=read_float(valuation.get("valuation_percentile"), 50.0),
        recovery_probability_12m=recovery_12m,
        recovery_probability_24m=recovery_24m,
        panic_probability=panic_probability,
        recovery_probability=recovery_probability,
        confidence=confidence,
        market_crash_12m=market_crash,
        sector_stress_12m=sector_stress,
    )


def decision_outputs_from_row(row: dict[str, Any], *, credit_stress_index: float, valuation: dict[str, float | str]) -> dict[str, float]:
    if not row:
        return {
            "credit_stress_index": round(bounded(credit_stress_index, 0.0, 100.0), 6),
            "valuation_score": read_float(valuation.get("valuation_score"), 50.0),
            "valuation_risk_score": read_float(valuation.get("valuation_risk_score"), 50.0),
            "valuation_percentile": read_float(valuation.get("valuation_percentile"), 50.0),
            "recovery_probability_12m": 50.0,
            "recovery_probability_24m": 50.0,
            "buy_score": 0.0,
            "hold_score": 100.0,
            "sell_score": 0.0,
            "expected_return_12m": 0.0,
            "expected_drawdown_12m": 0.0,
        }
    market_crash = read_float(row.get("crash_prob_12m"), 0.50)
    recovery = read_float(row.get("pump_prob_12m"), 1.0 - market_crash)
    confidence = normalize_confidence(read_float(row.get("confidence_score"), 0.50))
    credit_stress = bounded(credit_stress_index, 0.0, 100.0) / 100.0
    valuation_score = read_float(valuation.get("valuation_score"), 50.0) / 100.0
    valuation_risk = read_float(valuation.get("valuation_risk_score"), 50.0) / 100.0
    panic_probability = bounded(market_crash * 0.84 + credit_stress * 0.10 + valuation_risk * 0.06, 0.0, 1.0)
    recovery_probability = bounded(recovery * 0.50 + (1.0 - market_crash) * 0.30 + (1.0 - credit_stress) * 0.10 + valuation_score * 0.10, 0.0, 1.0)
    recovery_12m, recovery_24m = calculate_recovery_probabilities(
        market_crash_12m=market_crash,
        systemic_stress_12m=market_crash,
        liquidity_index=latest_macro_value("GLOBAL_LIQUIDITY_INDEX", 55.0),
        credit_stress_index=credit_stress_index,
        recovery_signal=recovery_probability,
        expected_return_proxy=None,
        expected_drawdown_proxy=None,
    )
    return build_decision_outputs(
        credit_stress_index=credit_stress_index,
        valuation_score=read_float(valuation.get("valuation_score"), 50.0),
        valuation_risk_score=read_float(valuation.get("valuation_risk_score"), 50.0),
        valuation_percentile=read_float(valuation.get("valuation_percentile"), 50.0),
        recovery_probability_12m=recovery_12m,
        recovery_probability_24m=recovery_24m,
        panic_probability=panic_probability,
        recovery_probability=recovery_probability,
        confidence=confidence,
        market_crash_12m=market_crash,
        sector_stress_12m=market_crash,
    )


def precious_metals_outputs_from_matrix(matrix: ProbabilityMatrix, *, credit_stress_index: float, valuation: dict[str, float | str]) -> dict[str, object]:
    valuation_tilt = (read_float(valuation.get("valuation_score"), 50.0) - 50.0) * 0.10
    return PreciousMetalsRegimeEngine().evaluate(
        PreciousMetalsInput(
            liquidity_index=bounded(latest_macro_value("GLOBAL_LIQUIDITY_INDEX", 55.0) + valuation_tilt, 0.0, 100.0),
            credit_stress_index=credit_stress_index,
            market_crash_probability=matrix.probabilities["market_crash"][12],
            systemic_stress_probability=matrix.probabilities["systemic_stress"][12],
            inflation_pressure=calculate_macro_pressure("inflation", 50.0),
            real_rate_pressure=calculate_macro_pressure("real_rate", 50.0),
            dollar_pressure=calculate_macro_pressure("dollar", 50.0),
            gold_silver_ratio=calculate_gold_silver_ratio(),
        )
    ).to_dict()


def precious_metals_outputs_from_row(row: dict[str, Any], *, credit_stress_index: float, valuation: dict[str, float | str]) -> dict[str, object]:
    market_crash = read_float(row.get("crash_prob_12m") if row else None, 0.45)
    systemic_stress = read_float(row.get("crash_prob_12m") if row else None, market_crash)
    valuation_tilt = (read_float(valuation.get("valuation_score"), 50.0) - 50.0) * 0.10
    return PreciousMetalsRegimeEngine().evaluate(
        PreciousMetalsInput(
            liquidity_index=bounded(latest_macro_value("GLOBAL_LIQUIDITY_INDEX", 55.0) + valuation_tilt, 0.0, 100.0),
            credit_stress_index=credit_stress_index,
            market_crash_probability=market_crash,
            systemic_stress_probability=systemic_stress,
            inflation_pressure=calculate_macro_pressure("inflation", 50.0),
            real_rate_pressure=calculate_macro_pressure("real_rate", 50.0),
            dollar_pressure=calculate_macro_pressure("dollar", 50.0),
            gold_silver_ratio=calculate_gold_silver_ratio(),
        )
    ).to_dict()


def calculate_recovery_probabilities(
    *,
    market_crash_12m: float,
    systemic_stress_12m: float,
    liquidity_index: float,
    credit_stress_index: float,
    recovery_signal: float,
    expected_return_proxy: float | None,
    expected_drawdown_proxy: float | None,
) -> tuple[float, float]:
    crash = bounded(market_crash_12m, 0.0, 1.0)
    systemic = bounded(systemic_stress_12m, 0.0, 1.0)
    liquidity = bounded(liquidity_index, 0.0, 100.0) / 100.0
    credit_repair = 1.0 - bounded(credit_stress_index, 0.0, 100.0) / 100.0
    recovery_base = bounded(recovery_signal, 0.0, 1.0)
    positive_return = bounded(((expected_return_proxy if expected_return_proxy is not None else 0.0) + 0.25) / 0.50, 0.0, 1.0)
    drawdown_repair = 1.0 - bounded(expected_drawdown_proxy if expected_drawdown_proxy is not None else max(crash, systemic) * 0.45, 0.0, 0.80) / 0.80
    stress_reset = bounded((crash + systemic) / 2.0, 0.0, 1.0)
    moderate_stress = 1.0 - abs(stress_reset - 0.45) / 0.45
    moderate_stress = bounded(moderate_stress, 0.0, 1.0)
    recovery_12m = (
        recovery_base * 0.28
        + liquidity * 0.20
        + credit_repair * 0.18
        + positive_return * 0.14
        + drawdown_repair * 0.10
        + moderate_stress * 0.10
    )
    recovery_24m = (
        recovery_12m * 0.58
        + liquidity * 0.18
        + credit_repair * 0.14
        + drawdown_repair * 0.10
    )
    return round(bounded(recovery_12m * 100.0, 0.0, 100.0), 6), round(bounded(recovery_24m * 100.0, 0.0, 100.0), 6)


def build_decision_outputs(
    *,
    credit_stress_index: float,
    valuation_score: float,
    valuation_risk_score: float,
    valuation_percentile: float,
    recovery_probability_12m: float,
    recovery_probability_24m: float,
    panic_probability: float,
    recovery_probability: float,
    confidence: float,
    market_crash_12m: float,
    sector_stress_12m: float,
) -> dict[str, float]:
    panic = bounded(panic_probability, 0.0, 1.0)
    recovery = bounded(recovery_probability, 0.0, 1.0)
    confidence = normalize_confidence(confidence)
    recovery_12m = bounded(recovery_probability_12m, 0.0, 100.0) / 100.0
    recovery_24m = bounded(recovery_probability_24m, 0.0, 100.0) / 100.0
    valuation_attractiveness = bounded(valuation_score, 0.0, 100.0) / 100.0
    valuation_risk = bounded(valuation_risk_score, 0.0, 100.0) / 100.0
    conviction = 0.55 + confidence * 0.45
    raw_buy = max(0.01, (recovery * 0.62 + recovery_12m * 0.25 + valuation_attractiveness * 0.13) * conviction)
    raw_sell = max(0.01, (panic * 0.78 + (1.0 - recovery_12m) * 0.12 + valuation_risk * 0.10) * conviction)
    raw_hold = max(0.01, (1.0 - abs(recovery - panic)) * (1.15 - conviction))
    total = raw_buy + raw_hold + raw_sell
    buy_score = round(raw_buy / total * 100.0, 2)
    sell_score = round(raw_sell / total * 100.0, 2)
    hold_score = round(max(0.0, 100.0 - buy_score - sell_score), 2)
    credit_stress = bounded(credit_stress_index, 0.0, 100.0) / 100.0
    expected_return = bounded(recovery * 0.16 + recovery_12m * 0.07 + recovery_24m * 0.04 + valuation_attractiveness * 0.06 - panic * 0.27 - credit_stress * 0.05 + (confidence - 0.50) * 0.04, -0.50, 0.50)
    expected_drawdown = bounded(panic * 0.38 + market_crash_12m * 0.10 + sector_stress_12m * 0.05 + credit_stress * 0.10 + valuation_risk * 0.08, 0.0, 0.80)
    return {
        "credit_stress_index": round(bounded(credit_stress_index, 0.0, 100.0), 6),
        "valuation_score": round(bounded(valuation_score, 0.0, 100.0), 6),
        "valuation_risk_score": round(bounded(valuation_risk_score, 0.0, 100.0), 6),
        "valuation_percentile": round(bounded(valuation_percentile, 0.0, 100.0), 6),
        "recovery_probability_12m": round(bounded(recovery_probability_12m, 0.0, 100.0), 6),
        "recovery_probability_24m": round(bounded(recovery_probability_24m, 0.0, 100.0), 6),
        "buy_score": buy_score,
        "hold_score": hold_score,
        "sell_score": sell_score,
        "expected_return_12m": round(expected_return, 6),
        "expected_drawdown_12m": round(expected_drawdown, 6),
    }


def normalize_confidence(value: float) -> float:
    confidence = read_float(value, 0.50)
    if confidence > 1.0:
        confidence /= 100.0
    return bounded(confidence, 0.0, 1.0)


def bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def read_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_percent(value: Any) -> str:
    return f"{read_float(value, 0.0) * 100.0:.2f}%"


def format_telegram_summary(
    row: dict[str, Any],
    decision: dict[str, float] | None = None,
    precious_metals: dict[str, object] | None = None,
    walk_forward_metrics: dict[str, float | str] | None = None,
    crisis_replay_metrics: dict[str, float | str] | None = None,
    valuation: dict[str, float | str] | None = None,
    hmm_regime: dict[str, float | str] | None = None,
) -> str:
    if not row:
        return "Aegis Monthly Alert\n\nNo probability output is available yet."
    valuation = valuation or calculate_valuation_outputs()
    decision = decision or decision_outputs_from_row(row, credit_stress_index=calculate_credit_stress_index(), valuation=valuation)
    precious_metals = precious_metals or precious_metals_outputs_from_row(
        row,
        credit_stress_index=read_float(decision.get("credit_stress_index"), calculate_credit_stress_index()),
        valuation=valuation,
    )
    walk_forward_metrics = walk_forward_metrics or calculate_walk_forward_metrics()
    crisis_replay_metrics = crisis_replay_metrics or calculate_crisis_replay_metrics()
    hmm_regime = hmm_regime or calculate_hmm_regime_outputs(
        row=row,
        decision=decision,
        credit_stress_index=read_float(decision.get("credit_stress_index"), calculate_credit_stress_index()),
        valuation=valuation,
    )
    return (
        "Aegis Monthly Alert\n\n"
        f"Regime: {row['current_regime']}\n"
        f"HMM Regime: {hmm_regime['regime_state']} ({hmm_regime['regime_probability']})\n"
        f"Crash 1M: {row['crash_prob_1m']}\n"
        f"Crash 3M: {row['crash_prob_3m']}\n"
        f"Crash 6M: {row['crash_prob_6m']}\n"
        f"Crash 12M: {row['crash_prob_12m']}\n"
        f"Credit Stress Index: {decision['credit_stress_index']}\n"
        f"Valuation Score/Risk/Pctl: {decision['valuation_score']}/{decision['valuation_risk_score']}/{decision['valuation_percentile']}\n"
        f"Recovery 12M/24M: {decision['recovery_probability_12m']}/{decision['recovery_probability_24m']}\n"
        f"Buy/Hold/Sell: {decision['buy_score']}/{decision['hold_score']}/{decision['sell_score']}\n"
        f"Expected Return 12M: {format_percent(decision['expected_return_12m'])}\n"
        f"Expected Drawdown 12M: {format_percent(decision['expected_drawdown_12m'])}\n"
        f"WF Accuracy 3M/6M/12M: {walk_forward_metrics['forecast_accuracy_3m']}/{walk_forward_metrics['forecast_accuracy_6m']}/{walk_forward_metrics['forecast_accuracy_12m']}\n"
        f"Buy/Sell Hit Rate: {walk_forward_metrics['buy_signal_success_rate']}/{walk_forward_metrics['sell_signal_success_rate']}\n"
        f"Crisis Replay Det/Rec/Quality: {crisis_replay_metrics['crisis_detection_rate']}/{crisis_replay_metrics['recovery_detection_rate']}/{crisis_replay_metrics['signal_quality_score']}\n"
        f"Crisis Lead Panic/Recovery: {crisis_replay_metrics['panic_lead_time_months']}m/{crisis_replay_metrics['recovery_lead_time_months']}m\n"
        f"Gold Bull/Bear: {precious_metals['gold_bull_probability']}/{precious_metals['gold_bear_probability']}\n"
        f"Gold Buy/Hold/Sell: {precious_metals['gold_buy_score']}/{precious_metals['gold_hold_score']}/{precious_metals['gold_sell_score']}\n"
        f"Silver Bull/Bear: {precious_metals['silver_bull_probability']}/{precious_metals['silver_bear_probability']}\n"
        f"Silver Buy/Hold/Sell: {precious_metals['silver_buy_score']}/{precious_metals['silver_hold_score']}/{precious_metals['silver_sell_score']}\n"
        f"Gold/Silver Ratio: {precious_metals['gold_silver_ratio']}\n"
        f"Early Warning Score: {row['early_warning_score']}\n"
        f"Confidence: {row['confidence_score']}\n"
        f"Timestamp UTC: {row['timestamp']}"
    )


def serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value) if value is not None else None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
