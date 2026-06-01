from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterator

import psycopg2
from fastapi import FastAPI, HTTPException

from analytics.synthesis.probability_aggregator import (
    AggregatorInput,
    ProbabilityAggregator,
    ProbabilityMatrix,
    ProbabilityMatrixPersistenceAdapter,
)
from analytics.synthesis.scenario_engine import ScenarioEngine, ScenarioRun


app = FastAPI(title="Aegis Worker", version="1.0.0")


@app.get("/health")
def health() -> dict[str, Any]:
    database_configured = bool(os.getenv("DATABASE_URL"))
    return {
        "status": "ok" if database_configured else "missing_database_url",
        "service": "aegis-worker",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "database_configured": database_configured,
    }


@app.post("/run/probability")
def run_probability() -> dict[str, Any]:
    input_data = build_aggregator_input()
    matrix = ProbabilityAggregator().aggregate(input_data)
    with db_connection() as connection:
        ProbabilityMatrixPersistenceAdapter().persist(connection, matrix)
        connection.commit()
    return {
        "status": "ok",
        "timestamp_utc": matrix.timestamp.isoformat(),
        "early_warning_score": matrix.early_warning_score,
        "confidence_score": matrix.confidence_score,
        "systemic_stress_12m": matrix.probabilities["systemic_stress"][12],
    }


@app.post("/run/scenario")
def run_scenario() -> dict[str, Any]:
    input_data = build_aggregator_input()
    run = ScenarioEngine().run(input_data, [input_data])
    payload = scenario_payload(run)
    with db_connection() as connection:
        persist_exception_log(
            connection,
            source_name="aegis_worker",
            field_name="scenario_outputs",
            exception_type="SCENARIO_GENERATION_OUTPUTS",
            payload=payload,
            severity="LOW",
        )
        connection.commit()
    return {
        "status": "ok",
        "timestamp_utc": run.timestamp.isoformat(),
        "scenario_count": len(run.scenarios),
        "counterfactual_count": len(run.counterfactual_paths),
    }


@app.post("/run/monthly-report")
def run_monthly_report() -> dict[str, Any]:
    probability = run_probability()
    scenario = run_scenario()
    latest = latest_probability_row()
    return {
        "status": "ok",
        "probability": probability,
        "scenario": scenario,
        "telegram_summary": format_telegram_summary(latest),
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
    previous_systemic = latest_systemic_stress()
    return AggregatorInput(
        timestamp=datetime.now(timezone.utc),
        liquidity_index=55.0,
        liquidity_transmission_score=50.0,
        leading_diffusion_index=0.05,
        hhi_concentration_score=0.30,
        discovery_score=50.0,
        backtest_sharpe=0.50,
        backtest_win_rate=0.55,
        regime_probability=0.45,
        volatility_index=35.0,
        crypto_liquidity_index=50.0,
        previous_systemic_stress_12m=previous_systemic,
    )


def latest_systemic_stress() -> float | None:
    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT crash_prob_12m FROM probability_matrix_outputs_v3 "
                    "ORDER BY timestamp DESC LIMIT 1"
                )
                row = cursor.fetchone()
                return float(row[0]) if row else None
    except Exception:
        return None


def latest_probability_row() -> dict[str, Any]:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    timestamp,
                    target_scope,
                    crash_prob_1m,
                    crash_prob_3m,
                    crash_prob_6m,
                    crash_prob_12m,
                    early_warning_score,
                    confidence_score,
                    current_regime
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
        "early_warning_score",
        "confidence_score",
        "current_regime",
    )
    return {key: serialize_value(value) for key, value in zip(keys, row)}


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
                timestamp,
                source_name,
                field_name,
                exception_type,
                bad_value_raw,
                severity
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                datetime.now(timezone.utc),
                source_name,
                field_name,
                exception_type,
                json.dumps(payload, sort_keys=True),
                severity,
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
        "counterfactual_paths": [
            {
                "action_name": path.action_name,
                "systemic_stress_12m": path.systemic_stress_12m,
                "risk_reduction": path.risk_reduction,
            }
            for path in run.counterfactual_paths
        ],
    }


def format_telegram_summary(row: dict[str, Any]) -> str:
    if not row:
        return "Aegis Monthly Alert\n\nNo probability output is available yet."
    return (
        "Aegis Monthly Alert\n\n"
        f"Regime: {row['current_regime']}\n"
        f"Crash 1M: {row['crash_prob_1m']}\n"
        f"Crash 3M: {row['crash_prob_3m']}\n"
        f"Crash 6M: {row['crash_prob_6m']}\n"
        f"Crash 12M: {row['crash_prob_12m']}\n"
        f"Early Warning Score: {row['early_warning_score']}\n"
        f"Confidence: {row['confidence_score']}\n"
        f"Timestamp UTC: {row['timestamp']}"
    )


def serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value) if value is not None else None
