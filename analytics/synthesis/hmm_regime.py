from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from analytics.common import clamp


REGIME_STATES = ("RECOVERY", "EXPANSION", "LATE_CYCLE", "RECESSION", "PANIC")
FEATURE_NAMES = (
    "liquidity",
    "credit_stress",
    "recovery_probability",
    "valuation_score",
    "expected_return",
    "expected_drawdown",
    "panic_probability",
)


@dataclass(frozen=True)
class HMMRegimeInput:
    liquidity_index: float | None = None
    credit_stress_index: float | None = None
    recovery_probability: float | None = None
    valuation_score: float | None = None
    expected_return: float | None = None
    expected_drawdown: float | None = None
    panic_probability: float | None = None


@dataclass(frozen=True)
class HMMRegimeResult:
    regime_state: str
    regime_probability: float
    regime_confidence: float
    validation_method: str

    def to_dict(self) -> dict[str, float | str]:
        return {
            "regime_state": self.regime_state,
            "regime_probability": self.regime_probability,
            "regime_confidence": self.regime_confidence,
            "hmm_regime_validation_method": self.validation_method,
        }


class HMMRegimeModel:
    def __init__(
        self,
        *,
        transition_matrix: dict[str, dict[str, float]] | None = None,
        emission_means: dict[str, tuple[float, ...]] | None = None,
        emission_variance: float = 0.055,
    ) -> None:
        self.transition_matrix = transition_matrix or DEFAULT_TRANSITIONS
        self.emission_means = emission_means or DEFAULT_EMISSIONS
        self.emission_variance = emission_variance

    def classify(self, current: HMMRegimeInput, history: Sequence[HMMRegimeInput] | None = None) -> HMMRegimeResult:
        sequence = list(history or [])[-24:] + [current]
        vectors = [feature_vector(item) for item in sequence]
        if len(vectors) >= 3:
            probabilities = self.forward_probabilities(vectors)
            method = (
                "True HMM forward inference over stored Aegis feature history; expected transitions: "
                "PANIC -> RECOVERY -> EXPANSION and EXPANSION -> LATE_CYCLE -> RECESSION/PANIC."
            )
        else:
            probabilities = self.forward_probabilities(vectors)
            method = "Safe HMM fallback: insufficient history, current feature vector evaluated against regime emission profiles."
        state, probability = max(probabilities.items(), key=lambda item: item[1])
        sorted_probs = sorted(probabilities.values(), reverse=True)
        confidence = sorted_probs[0] - (sorted_probs[1] if len(sorted_probs) > 1 else 0.0)
        return HMMRegimeResult(
            regime_state=state,
            regime_probability=round(clamp(probability, 0.0, 1.0), 6),
            regime_confidence=round(clamp(confidence, 0.0, 1.0), 6),
            validation_method=method,
        )

    def forward_probabilities(self, vectors: Sequence[tuple[float, ...]]) -> dict[str, float]:
        probabilities = {state: 1.0 / len(REGIME_STATES) for state in REGIME_STATES}
        for vector in vectors:
            updated = {}
            for state in REGIME_STATES:
                transition_probability = sum(
                    probabilities[previous] * self.transition_matrix[previous][state]
                    for previous in REGIME_STATES
                )
                updated[state] = transition_probability * self.emission_probability(state, vector)
            probabilities = normalize(updated)
        return probabilities

    def emission_probability(self, state: str, vector: tuple[float, ...]) -> float:
        mean = self.emission_means[state]
        variance = self.emission_variance
        distance = sum((value - mean[index]) ** 2 for index, value in enumerate(vector))
        return math.exp(-distance / max(variance, 1e-6))


def feature_vector(input_data: HMMRegimeInput) -> tuple[float, ...]:
    return (
        index_0_100(input_data.liquidity_index, 55.0) / 100.0,
        index_0_100(input_data.credit_stress_index, 45.0) / 100.0,
        index_0_100(input_data.recovery_probability, 50.0) / 100.0,
        index_0_100(input_data.valuation_score, 50.0) / 100.0,
        clamp(((input_data.expected_return if input_data.expected_return is not None else 0.0) + 0.30) / 0.60, 0.0, 1.0),
        clamp((input_data.expected_drawdown if input_data.expected_drawdown is not None else 0.25) / 0.80, 0.0, 1.0),
        probability_0_1(input_data.panic_probability, 0.45),
    )


def normalize(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in values.values())
    if total <= 0.0:
        return {state: 1.0 / len(values) for state in values}
    return {state: max(0.0, value) / total for state, value in values.items()}


def index_0_100(value: float | None, default: float) -> float:
    return clamp(default if value is None else float(value), 0.0, 100.0)


def probability_0_1(value: float | None, default: float) -> float:
    if value is None:
        return default
    parsed = float(value)
    if parsed > 1.0:
        parsed /= 100.0
    return clamp(parsed, 0.0, 1.0)


DEFAULT_EMISSIONS = {
    "RECOVERY": (0.62, 0.38, 0.72, 0.62, 0.66, 0.28, 0.36),
    "EXPANSION": (0.72, 0.25, 0.62, 0.52, 0.70, 0.18, 0.22),
    "LATE_CYCLE": (0.52, 0.45, 0.42, 0.28, 0.52, 0.32, 0.42),
    "RECESSION": (0.34, 0.72, 0.30, 0.42, 0.30, 0.56, 0.68),
    "PANIC": (0.22, 0.88, 0.20, 0.58, 0.18, 0.76, 0.86),
}


DEFAULT_TRANSITIONS = {
    "RECOVERY": {"RECOVERY": 0.46, "EXPANSION": 0.34, "LATE_CYCLE": 0.08, "RECESSION": 0.07, "PANIC": 0.05},
    "EXPANSION": {"RECOVERY": 0.08, "EXPANSION": 0.62, "LATE_CYCLE": 0.20, "RECESSION": 0.07, "PANIC": 0.03},
    "LATE_CYCLE": {"RECOVERY": 0.05, "EXPANSION": 0.16, "LATE_CYCLE": 0.48, "RECESSION": 0.22, "PANIC": 0.09},
    "RECESSION": {"RECOVERY": 0.20, "EXPANSION": 0.06, "LATE_CYCLE": 0.04, "RECESSION": 0.48, "PANIC": 0.22},
    "PANIC": {"RECOVERY": 0.28, "EXPANSION": 0.03, "LATE_CYCLE": 0.02, "RECESSION": 0.24, "PANIC": 0.43},
}
