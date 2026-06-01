from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean
from typing import Sequence

from analytics.common import clip_probability


@dataclass(frozen=True)
class CalibrationMetrics:
    brier_score: float
    expected_calibration_error: float


class PlattScaler:
    def __init__(self, *, learning_rate: float = 0.05, iterations: int = 1000) -> None:
        if learning_rate <= 0.0 or iterations <= 0:
            raise ValueError("learning_rate and iterations must be positive")
        self.learning_rate = learning_rate
        self.iterations = iterations
        self.intercept = 0.0
        self.slope = 1.0

    def fit(self, scores: Sequence[float], outcomes: Sequence[int]) -> "PlattScaler":
        x, y = aligned_float_int(scores, outcomes)
        if not x:
            raise ValueError("scores must not be empty")
        self.intercept = 0.0
        self.slope = 1.0
        for _ in range(self.iterations):
            intercept_gradient = 0.0
            slope_gradient = 0.0
            for score, outcome in zip(x, y):
                prediction = sigmoid(self.intercept + self.slope * score)
                error = prediction - outcome
                intercept_gradient += error
                slope_gradient += error * score
            scale = 1.0 / len(x)
            self.intercept -= self.learning_rate * intercept_gradient * scale
            self.slope -= self.learning_rate * slope_gradient * scale
        return self

    def predict(self, scores: Sequence[float]) -> list[float]:
        return [clip_probability(sigmoid(self.intercept + self.slope * float(score))) for score in scores]


class IsotonicScaler:
    def __init__(self) -> None:
        self.thresholds: list[float] = []
        self.values: list[float] = []

    def fit(self, scores: Sequence[float], outcomes: Sequence[int]) -> "IsotonicScaler":
        x, y = aligned_float_int(scores, outcomes)
        pairs = sorted(zip(x, y), key=lambda item: item[0])
        if not pairs:
            raise ValueError("scores must not be empty")

        blocks: list[dict[str, float]] = []
        for score, outcome in pairs:
            blocks.append({"start": score, "end": score, "sum": float(outcome), "count": 1.0})
            while len(blocks) >= 2 and block_average(blocks[-2]) > block_average(blocks[-1]):
                right = blocks.pop()
                left = blocks.pop()
                blocks.append(
                    {
                        "start": left["start"],
                        "end": right["end"],
                        "sum": left["sum"] + right["sum"],
                        "count": left["count"] + right["count"],
                    }
                )

        self.thresholds = [block["end"] for block in blocks]
        self.values = [clip_probability(block_average(block)) for block in blocks]
        return self

    def predict(self, scores: Sequence[float]) -> list[float]:
        if not self.thresholds:
            raise ValueError("IsotonicScaler must be fit before predict")
        predictions: list[float] = []
        for score in scores:
            value = self.values[-1]
            for threshold, candidate in zip(self.thresholds, self.values):
                if float(score) <= threshold:
                    value = candidate
                    break
            predictions.append(clip_probability(value))
        return predictions


class BetaCalibrator:
    def __init__(self) -> None:
        self.positive_alpha = 1.0
        self.negative_alpha = 1.0

    def fit(self, probabilities: Sequence[float], outcomes: Sequence[int]) -> "BetaCalibrator":
        probs, y = aligned_float_int(probabilities, outcomes)
        positives = [clip_probability(prob) for prob, outcome in zip(probs, y) if outcome == 1]
        negatives = [clip_probability(prob) for prob, outcome in zip(probs, y) if outcome == 0]
        self.positive_alpha = mean(positives) if positives else 0.5
        self.negative_alpha = 1.0 - (mean(negatives) if negatives else 0.5)
        return self

    def predict(self, probabilities: Sequence[float]) -> list[float]:
        calibrated: list[float] = []
        for probability in probabilities:
            clipped = clip_probability(probability)
            numerator = clipped * self.positive_alpha
            denominator = numerator + (1.0 - clipped) * self.negative_alpha
            calibrated.append(clip_probability(numerator / denominator if denominator else clipped))
        return calibrated


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    probs, y = aligned_float_int(probabilities, outcomes)
    if not probs:
        return 0.0
    return round(mean((clip_probability(prob) - outcome) ** 2 for prob, outcome in zip(probs, y)), 10)


def expected_calibration_error(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    bins: int = 10,
) -> float:
    if bins <= 0:
        raise ValueError("bins must be positive")
    probs, y = aligned_float_int(probabilities, outcomes)
    if not probs:
        return 0.0
    total = len(probs)
    ece = 0.0
    for bin_index in range(bins):
        lower = bin_index / bins
        upper = (bin_index + 1) / bins
        if bin_index == bins - 1:
            members = [
                (prob, outcome)
                for prob, outcome in zip(probs, y)
                if lower <= clip_probability(prob) <= upper
            ]
        else:
            members = [
                (prob, outcome)
                for prob, outcome in zip(probs, y)
                if lower <= clip_probability(prob) < upper
            ]
        if not members:
            continue
        confidence = mean(clip_probability(prob) for prob, _outcome in members)
        accuracy = mean(outcome for _prob, outcome in members)
        ece += len(members) / total * abs(confidence - accuracy)
    return round(ece, 10)


def evaluate_calibration(probabilities: Sequence[float], outcomes: Sequence[int]) -> CalibrationMetrics:
    return CalibrationMetrics(
        brier_score=brier_score(probabilities, outcomes),
        expected_calibration_error=expected_calibration_error(probabilities, outcomes),
    )


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def aligned_float_int(scores: Sequence[float], outcomes: Sequence[int]) -> tuple[list[float], list[int]]:
    length = min(len(scores), len(outcomes))
    return [float(scores[index]) for index in range(length)], [int(outcomes[index]) for index in range(length)]


def block_average(block: dict[str, float]) -> float:
    return block["sum"] / block["count"]
