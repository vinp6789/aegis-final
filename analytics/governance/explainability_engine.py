from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

from analytics.common import clamp, normalize_timestamp


ADDITIVE_TOLERANCE = 1e-5


@dataclass(frozen=True)
class FeatureVector:
    timestamp: datetime
    target_scope: str
    features: Mapping[str, float | int | None]
    prediction_value: float | None
    model_name: str = "ensemble"
    base_value: float | None = None


@dataclass(frozen=True)
class DriverAttribution:
    feature_name: str
    feature_value: float
    attribution: float
    absolute_attribution: float
    contribution_share: float


@dataclass(frozen=True)
class ExplanationResult:
    timestamp: datetime
    target_scope: str
    model_name: str
    prediction_value: float
    base_value: float
    additive_error: float
    additive_valid: bool
    driver_attributions: list[DriverAttribution]
    confidence_breakdown: dict[str, float]


@dataclass(frozen=True)
class ForecastDriverShift:
    feature_name: str
    previous_attribution: float
    current_attribution: float
    attribution_delta: float
    absolute_delta: float


@dataclass(frozen=True)
class ForecastDiffResult:
    previous_timestamp: datetime
    current_timestamp: datetime
    prediction_delta: float
    base_value_delta: float
    top_driver_shifts: list[ForecastDriverShift]


@dataclass(frozen=True)
class ForecastExplanationReport:
    timestamp: datetime
    target_scope: str
    model_name: str
    summary: str
    primary_drivers: list[str]
    analog_summary: str
    confidence_breakdown: dict[str, float]


class ShapProvider(Protocol):
    def explain(
        self,
        model: Any,
        feature_names: Sequence[str],
        feature_values: Sequence[float],
        background: Sequence[Sequence[float]],
    ) -> tuple[float, Sequence[float]]:
        ...


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


class TreeShapProvider:
    def explain(
        self,
        model: Any,
        feature_names: Sequence[str],
        feature_values: Sequence[float],
        background: Sequence[Sequence[float]],
    ) -> tuple[float, Sequence[float]]:
        try:
            import shap  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional environment package.
            raise RuntimeError("shap is required for live TreeSHAP extraction") from exc

        explainer = shap.TreeExplainer(model, data=list(background) or None)
        shap_values = explainer.shap_values([list(feature_values)])
        values = shap_values[0] if isinstance(shap_values, list) else shap_values[0]
        expected = explainer.expected_value
        if isinstance(expected, list):
            expected = expected[0]
        return float(expected), [float(value) for value in values]


class ExplainabilityEngine:
    def __init__(
        self,
        *,
        shap_provider: ShapProvider | None = None,
        additive_tolerance: float = ADDITIVE_TOLERANCE,
    ) -> None:
        if additive_tolerance <= 0.0:
            raise ValueError("additive_tolerance must be positive")
        self.shap_provider = shap_provider or TreeShapProvider()
        self.additive_tolerance = additive_tolerance

    def explain_from_shap_values(
        self,
        vector: FeatureVector,
        *,
        shap_values: Mapping[str, float | int | None],
        base_value: float | None = None,
    ) -> ExplanationResult:
        clean_features = clean_feature_map(vector.features)
        ordered_names = list(clean_features)
        values = [float(shap_values.get(name, 0.0) or 0.0) for name in ordered_names]
        base = clean_number(base_value if base_value is not None else vector.base_value, 0.0)
        prediction = clean_number(vector.prediction_value, base + sum(values))
        return build_explanation(
            timestamp=vector.timestamp,
            target_scope=vector.target_scope,
            model_name=vector.model_name,
            prediction_value=prediction,
            base_value=base,
            feature_values=clean_features,
            shap_values=dict(zip(ordered_names, values)),
            additive_tolerance=self.additive_tolerance,
        )

    def explain_model(
        self,
        model: Any,
        vector: FeatureVector,
        *,
        background: Sequence[Mapping[str, float | int | None]] | None = None,
    ) -> ExplanationResult:
        clean_features = clean_feature_map(vector.features)
        names = list(clean_features)
        values = [clean_features[name] for name in names]
        background_rows = [
            [clean_feature_map(row).get(name, 0.0) for name in names]
            for row in (background or ())
        ]
        base_value, shap_values = self.shap_provider.explain(model, names, values, background_rows)
        return build_explanation(
            timestamp=vector.timestamp,
            target_scope=vector.target_scope,
            model_name=vector.model_name,
            prediction_value=clean_number(vector.prediction_value, base_value + sum(shap_values)),
            base_value=base_value,
            feature_values=clean_features,
            shap_values=dict(zip(names, shap_values)),
            additive_tolerance=self.additive_tolerance,
        )

    def driver_attribution_matrix(self, explanations: Sequence[ExplanationResult]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for explanation in explanations:
            for attribution in explanation.driver_attributions:
                rows.append(
                    {
                        "timestamp": explanation.timestamp,
                        "target_scope": explanation.target_scope,
                        "model_name": explanation.model_name,
                        "feature_name": attribution.feature_name,
                        "feature_value": attribution.feature_value,
                        "attribution": attribution.attribution,
                        "contribution_share": attribution.contribution_share,
                    }
                )
        return rows

    def forecast_diff(
        self,
        previous: ExplanationResult,
        current: ExplanationResult,
        *,
        top_n: int = 5,
    ) -> ForecastDiffResult:
        if top_n <= 0:
            raise ValueError("top_n must be positive")
        previous_map = {item.feature_name: item.attribution for item in previous.driver_attributions}
        current_map = {item.feature_name: item.attribution for item in current.driver_attributions}
        shifts = []
        for feature_name in sorted(set(previous_map) | set(current_map)):
            prev = previous_map.get(feature_name, 0.0)
            curr = current_map.get(feature_name, 0.0)
            delta = curr - prev
            shifts.append(
                ForecastDriverShift(
                    feature_name=feature_name,
                    previous_attribution=round(prev, 10),
                    current_attribution=round(curr, 10),
                    attribution_delta=round(delta, 10),
                    absolute_delta=round(abs(delta), 10),
                )
            )
        shifts.sort(key=lambda item: item.absolute_delta, reverse=True)
        return ForecastDiffResult(
            previous_timestamp=previous.timestamp,
            current_timestamp=current.timestamp,
            prediction_delta=round(current.prediction_value - previous.prediction_value, 10),
            base_value_delta=round(current.base_value - previous.base_value, 10),
            top_driver_shifts=shifts[:top_n],
        )

    def explanation_report(
        self,
        explanation: ExplanationResult,
        *,
        analog_summaries: Sequence[str] | None = None,
    ) -> ForecastExplanationReport:
        primary = [item.feature_name for item in explanation.driver_attributions[:3]]
        analog_summary = "; ".join(analog_summaries or ()) or "No historical analog supplied"
        summary = (
            f"{explanation.model_name} explains {explanation.target_scope} "
            f"with {len(explanation.driver_attributions)} bounded driver attributions."
        )
        return ForecastExplanationReport(
            timestamp=explanation.timestamp,
            target_scope=explanation.target_scope,
            model_name=explanation.model_name,
            summary=summary,
            primary_drivers=primary,
            analog_summary=analog_summary,
            confidence_breakdown=explanation.confidence_breakdown,
        )


class ExplainabilityPersistenceAdapter:
    table_name = "data_quality_exceptions"
    columns = (
        "timestamp",
        "source_name",
        "field_name",
        "exception_type",
        "bad_value_raw",
        "severity",
    )

    def to_row(self, explanation: ExplanationResult) -> dict[str, Any]:
        payload = {
            "target_scope": explanation.target_scope,
            "model_name": explanation.model_name,
            "prediction_value": explanation.prediction_value,
            "base_value": explanation.base_value,
            "additive_error": explanation.additive_error,
            "additive_valid": explanation.additive_valid,
            "primary_drivers": [
                {
                    "feature_name": item.feature_name,
                    "attribution": item.attribution,
                    "contribution_share": item.contribution_share,
                }
                for item in explanation.driver_attributions[:5]
            ],
            "confidence_breakdown": explanation.confidence_breakdown,
        }
        return {
            "timestamp": normalize_timestamp(explanation.timestamp),
            "source_name": "explainability_engine",
            "field_name": explanation.model_name,
            "exception_type": "EXPLAINABILITY_ADDITIVE_FAILURE"
            if not explanation.additive_valid
            else "EXPLAINABILITY_DECISION_LOG",
            "bad_value_raw": json.dumps(payload, sort_keys=True),
            "severity": "CRITICAL" if not explanation.additive_valid else "LOW",
        }

    def persist(self, connection: DbConnection, explanation: ExplanationResult) -> None:
        row = self.to_row(explanation)
        placeholders = ", ".join(["%s"] * len(self.columns))
        sql = f"INSERT INTO {self.table_name} ({', '.join(self.columns)}) VALUES ({placeholders})"
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(row[column] for column in self.columns))


def build_explanation(
    *,
    timestamp: datetime,
    target_scope: str,
    model_name: str,
    prediction_value: float,
    base_value: float,
    feature_values: Mapping[str, float],
    shap_values: Mapping[str, float],
    additive_tolerance: float,
) -> ExplanationResult:
    reconstruction = base_value + sum(float(value) for value in shap_values.values())
    additive_error = abs(prediction_value - reconstruction)
    total_abs = sum(abs(float(value)) for value in shap_values.values())
    attributions = [
        DriverAttribution(
            feature_name=name,
            feature_value=round(clean_number(feature_values.get(name), 0.0), 10),
            attribution=round(clean_number(shap_values.get(name), 0.0), 10),
            absolute_attribution=round(abs(clean_number(shap_values.get(name), 0.0)), 10),
            contribution_share=round(
                abs(clean_number(shap_values.get(name), 0.0)) / total_abs if total_abs else 0.0,
                10,
            ),
        )
        for name in feature_values
    ]
    attributions.sort(key=lambda item: item.absolute_attribution, reverse=True)
    return ExplanationResult(
        timestamp=normalize_timestamp(timestamp),
        target_scope=target_scope,
        model_name=model_name,
        prediction_value=round(clean_number(prediction_value, 0.0), 10),
        base_value=round(clean_number(base_value, 0.0), 10),
        additive_error=round(additive_error, 12),
        additive_valid=additive_error <= additive_tolerance,
        driver_attributions=attributions,
        confidence_breakdown=confidence_breakdown(
            additive_error=additive_error,
            additive_tolerance=additive_tolerance,
            total_abs=total_abs,
            driver_count=len(attributions),
        ),
    )


def confidence_breakdown(
    *,
    additive_error: float,
    additive_tolerance: float,
    total_abs: float,
    driver_count: int,
) -> dict[str, float]:
    additive_quality = 1.0 - clamp(additive_error / additive_tolerance, 0.0, 1.0)
    driver_coverage = clamp(total_abs / (total_abs + 0.10), 0.0, 1.0) if total_abs else 0.0
    sparsity_quality = clamp(1.0 - max(driver_count - 20, 0) / 50.0, 0.0, 1.0)
    return {
        "additive_quality": round(additive_quality, 6),
        "driver_coverage": round(driver_coverage, 6),
        "sparsity_quality": round(sparsity_quality, 6),
    }


def clean_feature_map(values: Mapping[str, float | int | None]) -> dict[str, float]:
    clean: dict[str, float] = {}
    for key in sorted(values):
        clean[key] = clean_number(values[key], 0.0)
    return clean


def clean_number(value: float | int | None, default: float) -> float:
    if value is None:
        return default
    parsed = float(value)
    if math.isnan(parsed):
        return default
    return parsed
