from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Mapping, Sequence

import numpy as np


SUPPORTED_HORIZONS_MONTHS = (1, 3, 6, 9, 12)


@dataclass(frozen=True)
class CandidateFeature:
    feature_name: str
    target_scope: str
    values: Sequence[float | int | None]


@dataclass(frozen=True)
class StationarityResult:
    test_name: str
    test_statistic: float
    p_value: float
    is_stationary: bool
    transformed_values: list[float]


@dataclass(frozen=True)
class CointegrationResult:
    test_name: str
    trace_statistic: float
    p_value: float
    is_cointegrated: bool


@dataclass(frozen=True)
class GrangerCausalityResult:
    lag: int
    f_statistic: float
    p_value: float
    causes_target: bool


@dataclass(frozen=True)
class TransferEntropyResult:
    lag: int
    entropy: float
    exceeds_threshold: bool


@dataclass(frozen=True)
class HorizonEvaluation:
    horizon_months: int
    observations: int
    correlation: float
    directional_accuracy: float
    information_coefficient: float
    score: float
    stationarity: StationarityResult | None = None
    cointegration: CointegrationResult | None = None
    granger: GrangerCausalityResult | None = None
    transfer_entropy: TransferEntropyResult | None = None


@dataclass(frozen=True)
class FeatureEvaluation:
    feature_name: str
    target_scope: str
    primary_horizon_months: int
    secondary_horizon_months: int
    current_score: float
    peak_score: float
    evaluated_at: datetime
    horizon_scores: Mapping[int, HorizonEvaluation]
    out_of_sample_validated: bool = False
    deterioration_detected: bool = False

    @property
    def primary_horizon(self) -> HorizonEvaluation | None:
        return self.horizon_scores.get(self.primary_horizon_months)

    @property
    def granger_p_value(self) -> float | None:
        primary = self.primary_horizon
        return primary.granger.p_value if primary and primary.granger else None

    @property
    def transfer_entropy_value(self) -> float | None:
        primary = self.primary_horizon
        return primary.transfer_entropy.entropy if primary and primary.transfer_entropy else None


@dataclass(frozen=True)
class DiscoveryResult:
    evaluated_features: list[FeatureEvaluation]
    rejected_features: dict[str, str]


@dataclass(frozen=True)
class DiscoveryConfig:
    horizons_months: tuple[int, ...] = SUPPORTED_HORIZONS_MONTHS
    primary_horizon_months: int = 3
    secondary_horizon_months: int = 6
    min_observations: int = 12
    max_missing_ratio: float = 0.2
    granger_lag: int = 2
    transfer_entropy_lag: int = 1
    transfer_entropy_bins: int = 3
    transfer_entropy_threshold: float = 0.02
    granger_p_threshold: float = 0.05

    def __post_init__(self) -> None:
        allowed = set(SUPPORTED_HORIZONS_MONTHS)
        if not set(self.horizons_months).issubset(allowed):
            raise ValueError(f"Unsupported horizons: {self.horizons_months}")
        if self.primary_horizon_months not in allowed:
            raise ValueError("primary_horizon_months must be one of 1, 3, 6, 9, 12")
        if self.secondary_horizon_months not in allowed:
            raise ValueError("secondary_horizon_months must be one of 1, 3, 6, 9, 12")
        if self.min_observations < 6:
            raise ValueError("min_observations must be at least 6")
        if not 0.0 <= self.max_missing_ratio <= 1.0:
            raise ValueError("max_missing_ratio must be between 0 and 1")
        if self.granger_lag < 1 or self.transfer_entropy_lag < 1:
            raise ValueError("causality lags must be positive")
        if self.transfer_entropy_bins < 2:
            raise ValueError("transfer_entropy_bins must be at least 2")


@dataclass
class DiscoveryEngine:
    config: DiscoveryConfig = field(default_factory=DiscoveryConfig)

    def evaluate(
        self,
        *,
        candidates: Sequence[CandidateFeature],
        target_returns: Mapping[int, Sequence[float | int | None]],
        evaluated_at: datetime | None = None,
    ) -> DiscoveryResult:
        timestamp = evaluated_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)

        evaluated: list[FeatureEvaluation] = []
        rejected: dict[str, str] = {}
        for candidate in candidates:
            try:
                evaluation = self.evaluate_candidate(
                    candidate=candidate,
                    target_returns=target_returns,
                    evaluated_at=timestamp,
                )
            except ValueError as exc:
                rejected[candidate.feature_name] = str(exc)
                continue
            evaluated.append(evaluation)

        evaluated.sort(key=lambda item: item.current_score, reverse=True)
        return DiscoveryResult(evaluated_features=evaluated, rejected_features=rejected)

    def evaluate_candidate(
        self,
        *,
        candidate: CandidateFeature,
        target_returns: Mapping[int, Sequence[float | int | None]],
        evaluated_at: datetime,
    ) -> FeatureEvaluation:
        feature_values = self._coerce_series(candidate.values, "feature values")
        if len(feature_values) < self.config.min_observations:
            raise ValueError("candidate has too few observations")

        missing_ratio = sum(value is None for value in candidate.values) / len(candidate.values)
        if missing_ratio > self.config.max_missing_ratio:
            raise ValueError("candidate exceeds missing-value limit")

        horizon_scores: dict[int, HorizonEvaluation] = {}
        for horizon in self.config.horizons_months:
            if horizon not in target_returns:
                continue
            target_values = self._coerce_series(target_returns[horizon], f"{horizon}m target")
            aligned_feature, aligned_target = self._align_non_null(feature_values, target_values)
            if len(aligned_feature) < self.config.min_observations:
                continue
            horizon_scores[horizon] = self._score_horizon(
                horizon_months=horizon,
                feature_values=aligned_feature,
                target_values=aligned_target,
            )

        if self.config.primary_horizon_months not in horizon_scores:
            raise ValueError("candidate lacks enough primary-horizon observations")

        primary = horizon_scores[self.config.primary_horizon_months]
        secondary = horizon_scores.get(self.config.secondary_horizon_months, primary)
        current_score = round(primary.score * 0.7 + secondary.score * 0.3, 2)
        peak_score = round(max(score.score for score in horizon_scores.values()), 2)

        return FeatureEvaluation(
            feature_name=candidate.feature_name,
            target_scope=candidate.target_scope,
            primary_horizon_months=self.config.primary_horizon_months,
            secondary_horizon_months=self.config.secondary_horizon_months,
            current_score=current_score,
            peak_score=peak_score,
            evaluated_at=evaluated_at,
            horizon_scores=horizon_scores,
        )

    def stationarity_test(self, values: Sequence[float | int]) -> StationarityResult:
        series = self._finite_array(values, "stationarity series")
        transformed = series
        statistic, p_value = self._adf_statistic(series)
        if p_value >= 0.05:
            transformed = np.diff(series)
            statistic, p_value = self._adf_statistic(transformed)
        return StationarityResult(
            test_name="Augmented Dickey-Fuller",
            test_statistic=round(float(statistic), 6),
            p_value=round(float(p_value), 6),
            is_stationary=bool(p_value < 0.05),
            transformed_values=[float(value) for value in transformed],
        )

    def johansen_cointegration_test(
        self,
        left: Sequence[float | int],
        right: Sequence[float | int],
    ) -> CointegrationResult:
        x = self._finite_array(left, "cointegration left")
        y = self._finite_array(right, "cointegration right")
        x, y = self._same_length(x, y)
        design = np.column_stack([np.ones(len(x)), x])
        beta = np.linalg.lstsq(design, y, rcond=None)[0]
        residuals = y - design @ beta
        if float(np.std(residuals)) < 1e-9:
            return CointegrationResult(
                test_name="Johansen cointegration residual proxy",
                trace_statistic=round(float(math.sqrt(len(x)) * 12.0), 6),
                p_value=0.0,
                is_cointegrated=True,
            )
        residual_stationarity = self.stationarity_test(residuals)
        trace_statistic = max(0.0, -math.log10(max(residual_stationarity.p_value, 1e-12))) * math.sqrt(len(x))
        return CointegrationResult(
            test_name="Johansen cointegration residual proxy",
            trace_statistic=round(float(trace_statistic), 6),
            p_value=residual_stationarity.p_value,
            is_cointegrated=residual_stationarity.p_value < 0.05,
        )

    def granger_causality_test(
        self,
        feature_values: Sequence[float | int],
        target_values: Sequence[float | int],
        *,
        lag: int | None = None,
    ) -> GrangerCausalityResult:
        selected_lag = lag or self.config.granger_lag
        x = self._finite_array(feature_values, "granger feature")
        y = self._finite_array(target_values, "granger target")
        x, y = self._same_length(x, y)
        if len(y) <= selected_lag * 3:
            raise ValueError("not enough observations for Granger causality")

        response = y[selected_lag:]
        restricted = self._lag_matrix(y, selected_lag)
        unrestricted = np.column_stack([restricted, self._lag_matrix(x, selected_lag)])
        restricted = np.column_stack([np.ones(len(restricted)), restricted])
        unrestricted = np.column_stack([np.ones(len(unrestricted)), unrestricted])

        rss_restricted = self._rss(response, restricted)
        rss_unrestricted = self._rss(response, unrestricted)
        df_num = selected_lag
        df_den = max(len(response) - unrestricted.shape[1], 1)
        if rss_unrestricted <= 1e-12:
            f_statistic = 1_000_000.0 if rss_restricted > 1e-12 else 0.0
        else:
            f_statistic = max(0.0, ((rss_restricted - rss_unrestricted) / df_num) / (rss_unrestricted / df_den))
        p_value = self._f_survival_approx(f_statistic, df_num, df_den)
        return GrangerCausalityResult(
            lag=selected_lag,
            f_statistic=round(float(f_statistic), 6),
            p_value=round(float(p_value), 6),
            causes_target=bool(p_value < self.config.granger_p_threshold),
        )

    def transfer_entropy(
        self,
        feature_values: Sequence[float | int],
        target_values: Sequence[float | int],
        *,
        lag: int | None = None,
    ) -> TransferEntropyResult:
        selected_lag = lag or self.config.transfer_entropy_lag
        x = self._finite_array(feature_values, "transfer entropy feature")
        y = self._finite_array(target_values, "transfer entropy target")
        x, y = self._same_length(x, y)
        if len(y) <= selected_lag + 2:
            raise ValueError("not enough observations for transfer entropy")

        x_bins = self._discretize(x, self.config.transfer_entropy_bins)
        y_bins = self._discretize(y, self.config.transfer_entropy_bins)
        triplets: dict[tuple[int, int, int], int] = {}
        pairs_yx: dict[tuple[int, int], int] = {}
        pairs_yy: dict[tuple[int, int], int] = {}
        y_history: dict[int, int] = {}

        for index in range(selected_lag, len(y_bins)):
            y_now = int(y_bins[index])
            y_prev = int(y_bins[index - selected_lag])
            x_prev = int(x_bins[index - selected_lag])
            triplets[(y_now, y_prev, x_prev)] = triplets.get((y_now, y_prev, x_prev), 0) + 1
            pairs_yx[(y_prev, x_prev)] = pairs_yx.get((y_prev, x_prev), 0) + 1
            pairs_yy[(y_now, y_prev)] = pairs_yy.get((y_now, y_prev), 0) + 1
            y_history[y_prev] = y_history.get(y_prev, 0) + 1

        total = sum(triplets.values())
        entropy = 0.0
        for (y_now, y_prev, x_prev), count in triplets.items():
            p_joint = count / total
            p_y_given_yx = count / pairs_yx[(y_prev, x_prev)]
            p_y_given_y = pairs_yy[(y_now, y_prev)] / y_history[y_prev]
            entropy += p_joint * math.log(max(p_y_given_yx, 1e-12) / max(p_y_given_y, 1e-12), 2)

        entropy = max(0.0, entropy)
        return TransferEntropyResult(
            lag=selected_lag,
            entropy=round(float(entropy), 6),
            exceeds_threshold=bool(entropy > self.config.transfer_entropy_threshold),
        )

    def _score_horizon(
        self,
        *,
        horizon_months: int,
        feature_values: Sequence[float],
        target_values: Sequence[float],
    ) -> HorizonEvaluation:
        stationarity = self.stationarity_test(feature_values)
        target_stationarity = self.stationarity_test(target_values)
        transformed_feature, transformed_target = self._same_length(
            np.asarray(stationarity.transformed_values, dtype=float),
            np.asarray(target_stationarity.transformed_values, dtype=float),
        )
        cointegration = self.johansen_cointegration_test(feature_values, target_values)
        granger = self.granger_causality_test(transformed_feature, transformed_target)
        transfer_entropy = self.transfer_entropy(transformed_feature, transformed_target)
        correlation = self._pearson(transformed_feature.tolist(), transformed_target.tolist())
        directional_accuracy = self._directional_accuracy(transformed_feature.tolist(), transformed_target.tolist())
        information_coefficient = abs(correlation)
        causality_bonus = 20.0 if granger.causes_target else 0.0
        entropy_bonus = min(transfer_entropy.entropy / max(self.config.transfer_entropy_threshold, 1e-9), 2.0) * 5.0
        score = round(
            information_coefficient * 65.0
            + directional_accuracy * 25.0
            + causality_bonus
            + entropy_bonus
            + min(len(transformed_feature) / 60.0, 1.0) * 10.0,
            2,
        )
        return HorizonEvaluation(
            horizon_months=horizon_months,
            observations=len(transformed_feature),
            correlation=round(correlation, 6),
            directional_accuracy=round(directional_accuracy, 6),
            information_coefficient=round(information_coefficient, 6),
            score=max(0.0, min(100.0, score)),
            stationarity=stationarity,
            cointegration=cointegration,
            granger=granger,
            transfer_entropy=transfer_entropy,
        )

    @staticmethod
    def _coerce_series(values: Sequence[float | int | None], label: str) -> list[float | None]:
        coerced: list[float | None] = []
        for value in values:
            if value is None:
                coerced.append(None)
                continue
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(f"{label} contains non-finite values")
            coerced.append(numeric)
        return coerced

    @staticmethod
    def _align_non_null(
        feature_values: Sequence[float | None],
        target_values: Sequence[float | None],
    ) -> tuple[list[float], list[float]]:
        length = min(len(feature_values), len(target_values))
        aligned_feature: list[float] = []
        aligned_target: list[float] = []
        for index in range(length):
            feature_value = feature_values[index]
            target_value = target_values[index]
            if feature_value is None or target_value is None:
                continue
            aligned_feature.append(feature_value)
            aligned_target.append(target_value)
        return aligned_feature, aligned_target

    @staticmethod
    def _finite_array(values: Sequence[float | int], label: str) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if array.ndim != 1 or len(array) < 3:
            raise ValueError(f"{label} must contain at least three observations")
        if not np.isfinite(array).all():
            raise ValueError(f"{label} contains non-finite values")
        return array

    @staticmethod
    def _same_length(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        length = min(len(left), len(right))
        if length < 3:
            raise ValueError("series overlap is too short")
        return left[-length:], right[-length:]

    @staticmethod
    def _adf_statistic(series: np.ndarray) -> tuple[float, float]:
        if len(series) < 6:
            return 0.0, 1.0
        if float(np.std(series)) == 0.0:
            return -1_000_000.0, 0.0
        delta = np.diff(series)
        y_lag = series[:-1]
        trend = np.arange(len(y_lag), dtype=float)
        design = np.column_stack([np.ones(len(y_lag)), trend, y_lag])
        beta, residuals, _rank, _singular = np.linalg.lstsq(design, delta, rcond=None)
        rss = float(residuals[0]) if len(residuals) else float(np.sum((delta - design @ beta) ** 2))
        df = max(len(delta) - design.shape[1], 1)
        sigma2 = rss / df
        covariance = sigma2 * np.linalg.pinv(design.T @ design)
        standard_error = math.sqrt(max(float(covariance[2, 2]), 1e-12))
        statistic = float(beta[2] / standard_error)
        p_value = min(1.0, math.exp(2.0 * statistic)) if statistic < 0.0 else 1.0
        return statistic, p_value

    @staticmethod
    def _lag_matrix(values: np.ndarray, lag: int) -> np.ndarray:
        rows = []
        for index in range(lag, len(values)):
            rows.append([values[index - step] for step in range(1, lag + 1)])
        return np.asarray(rows, dtype=float)

    @staticmethod
    def _rss(response: np.ndarray, design: np.ndarray) -> float:
        beta = np.linalg.lstsq(design, response, rcond=None)[0]
        residual = response - design @ beta
        return float(np.sum(residual ** 2))

    @staticmethod
    def _f_survival_approx(f_statistic: float, df_num: int, df_den: int) -> float:
        if f_statistic <= 0.0:
            return 1.0
        scaled = f_statistic * df_num / max(df_den, 1)
        return max(0.0, min(1.0, math.exp(-0.5 * f_statistic * df_num) * (1.0 + scaled)))

    @staticmethod
    def _discretize(values: np.ndarray, bins: int) -> np.ndarray:
        if float(np.std(values)) == 0.0:
            return np.zeros(len(values), dtype=int)
        quantiles = np.quantile(values, np.linspace(0.0, 1.0, bins + 1)[1:-1])
        return np.digitize(values, np.unique(quantiles), right=False)

    @staticmethod
    def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) < 2 or len(right) < 2:
            return 0.0
        left_deviation = pstdev(left)
        right_deviation = pstdev(right)
        if left_deviation == 0.0 or right_deviation == 0.0:
            return 0.0
        left_mean = mean(left)
        right_mean = mean(right)
        covariance = mean(
            (left_value - left_mean) * (right_value - right_mean)
            for left_value, right_value in zip(left, right)
        )
        return covariance / (left_deviation * right_deviation)

    @staticmethod
    def _directional_accuracy(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) < 2:
            return 0.0
        matches = 0
        comparisons = 0
        for index in range(1, len(left)):
            left_delta = left[index] - left[index - 1]
            right_delta = right[index] - right[index - 1]
            if left_delta == 0.0 or right_delta == 0.0:
                continue
            comparisons += 1
            if (left_delta > 0.0) == (right_delta > 0.0):
                matches += 1
        return matches / comparisons if comparisons else 0.0
