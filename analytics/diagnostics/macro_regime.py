from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, Sequence

from analytics.common import clamp
from analytics.diagnostics.breadth_engine import BreadthMetrics


class RegimeState(str, Enum):
    RISK_ON = "RISK_ON"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"
    CRISIS = "CRISIS"


@dataclass(frozen=True)
class RegimeInput:
    timestamp: datetime
    liquidity_index: float | None
    breadth: BreadthMetrics
    volatility_index: float | None


@dataclass(frozen=True)
class RegimeClassification:
    timestamp: datetime
    regime_state: RegimeState
    regime_probability: float
    leading_diffusion_index: float
    hhi_concentration_score: float
    stress_score: float


class DbConnection(Protocol):
    def cursor(self) -> Any:
        ...


class MacroRegimeClassifier:
    table_name = "macro_regime_classifications"

    centroids = {
        RegimeState.RISK_ON: 20.0,
        RegimeState.NEUTRAL: 45.0,
        RegimeState.RISK_OFF: 70.0,
        RegimeState.CRISIS: 90.0,
    }

    def classify(self, regime_input: RegimeInput) -> RegimeClassification:
        liquidity = clamp(clean_number(regime_input.liquidity_index, default=50.0), 0.0, 100.0)
        volatility = clamp(clean_number(regime_input.volatility_index, default=20.0), 0.0, 100.0)
        ldi = clamp(regime_input.breadth.leading_diffusion_index, -1.0, 1.0)
        hhi = clamp(regime_input.breadth.hhi_concentration_score, 0.0, 1.0)
        breadth_stress = (1.0 - ((ldi + 1.0) / 2.0)) * 100.0
        concentration_stress = hhi * 100.0
        liquidity_stress = 100.0 - liquidity
        stress = clamp(
            liquidity_stress * 0.35
            + breadth_stress * 0.30
            + concentration_stress * 0.15
            + volatility * 0.20,
            0.0,
            100.0,
        )
        state = min(self.centroids, key=lambda item: abs(stress - self.centroids[item]))
        probability = self._gmm_probability(stress, state)
        return RegimeClassification(
            timestamp=regime_input.timestamp.astimezone(timezone.utc),
            regime_state=state,
            regime_probability=round(probability, 6),
            leading_diffusion_index=round(ldi, 6),
            hhi_concentration_score=round(hhi, 6),
            stress_score=round(stress, 6),
        )

    def classify_many(self, inputs: Sequence[RegimeInput]) -> list[RegimeClassification]:
        return [self.classify(item) for item in inputs]

    def persist_classifications(
        self,
        connection: DbConnection,
        classifications: Sequence[RegimeClassification],
    ) -> None:
        if not classifications:
            return
        rows = [self.to_row(classification) for classification in classifications]
        columns = tuple(rows[0])
        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        with connection.cursor() as cursor:
            for row in rows:
                cursor.execute(sql, tuple(row[column] for column in columns))

    def to_row(self, classification: RegimeClassification) -> dict[str, Any]:
        return {
            "timestamp": classification.timestamp,
            "regime_state": classification.regime_state.value,
            "regime_probability": classification.regime_probability,
            "leading_diffusion_index": classification.leading_diffusion_index,
            "hhi_concentration_score": classification.hhi_concentration_score,
            "stress_score": classification.stress_score,
        }

    def _gmm_probability(self, stress_score: float, state: RegimeState) -> float:
        sigma = 14.0
        densities = {
            candidate: math.exp(-0.5 * ((stress_score - centroid) / sigma) ** 2)
            for candidate, centroid in self.centroids.items()
        }
        total = sum(densities.values())
        return clamp(densities[state] / total if total else 0.0, 0.0, 1.0)


def clean_number(value: float | int | None, *, default: float) -> float:
    if value is None:
        return default
    return float(value)
