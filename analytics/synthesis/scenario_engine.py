from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Mapping, Sequence

from analytics.common import clamp, normalize_timestamp
from analytics.synthesis.probability_aggregator import AggregatorInput, ProbabilityAggregator, ProbabilityMatrix


SCENARIO_NAMES = (
    "BASE",
    "BULL",
    "BEAR",
    "TAIL_RISK",
    "LIQUIDITY_SHOCK",
    "INDIA_STRESS",
    "CRYPTO_CRISIS",
)
REGIME_STATES = ("LOW_RISK", "WATCH", "ELEVATED", "HIGH_RISK", "CRISIS")


@dataclass(frozen=True)
class ScenarioConfig:
    mild_shock_std: float = 0.5
    moderate_shock_std: float = 1.0
    severe_shock_std: float = 2.0
    extreme_shock_std: float = 3.0
    counterfactual_top_k: int = 5
    action_step: float = 10.0
    max_mahalanobis: float = 6.0


@dataclass(frozen=True)
class ScenarioResult:
    scenario_name: str
    shocked_input: AggregatorInput
    probability_matrix: ProbabilityMatrix
    novelty_score: float


@dataclass(frozen=True)
class CounterfactualPath:
    action_name: str
    adjusted_input: AggregatorInput
    systemic_stress_12m: float
    risk_reduction: float


@dataclass(frozen=True)
class ScenarioRun:
    timestamp: datetime
    scenarios: list[ScenarioResult]
    transition_matrix: dict[str, dict[str, float]]
    counterfactual_paths: list[CounterfactualPath]


class ScenarioEngine:
    def __init__(
        self,
        *,
        config: ScenarioConfig | None = None,
        probability_aggregator: ProbabilityAggregator | None = None,
    ) -> None:
        self.config = config or load_threshold_config()
        self.probability_aggregator = probability_aggregator or ProbabilityAggregator()

    def run(self, base_input: AggregatorInput, historical_inputs: Sequence[AggregatorInput]) -> ScenarioRun:
        scenarios = [
            self.run_scenario(name, base_input, historical_inputs)
            for name in SCENARIO_NAMES
        ]
        transition_matrix = self.transition_matrix(scenarios)
        counterfactuals = self.counterfactual_paths(base_input)
        return ScenarioRun(
            timestamp=normalize_timestamp(base_input.timestamp),
            scenarios=scenarios,
            transition_matrix=transition_matrix,
            counterfactual_paths=counterfactuals,
        )

    def run_scenario(
        self,
        scenario_name: str,
        base_input: AggregatorInput,
        historical_inputs: Sequence[AggregatorInput],
    ) -> ScenarioResult:
        shocked = self.apply_scenario_shock(scenario_name, base_input)
        matrix = self.probability_aggregator.aggregate(shocked)
        novelty = self.scenario_novelty_score(shocked, historical_inputs)
        return ScenarioResult(
            scenario_name=scenario_name,
            shocked_input=shocked,
            probability_matrix=matrix,
            novelty_score=novelty,
        )

    def apply_scenario_shock(self, scenario_name: str, base_input: AggregatorInput) -> AggregatorInput:
        name = scenario_name.upper()
        if name == "BASE":
            return base_input
        if name == "BULL":
            return replace_input(
                base_input,
                liquidity_index=add_index(base_input.liquidity_index, self.config.moderate_shock_std * 10.0),
                crypto_liquidity_index=add_index(base_input.crypto_liquidity_index, self.config.mild_shock_std * 10.0),
                leading_diffusion_index=add_ldi(base_input.leading_diffusion_index, 0.20),
                volatility_index=add_index(base_input.volatility_index, -self.config.mild_shock_std * 10.0),
            )
        if name == "BEAR":
            return replace_input(
                base_input,
                liquidity_index=add_index(base_input.liquidity_index, -self.config.moderate_shock_std * 10.0),
                leading_diffusion_index=add_ldi(base_input.leading_diffusion_index, -0.25),
                volatility_index=add_index(base_input.volatility_index, self.config.moderate_shock_std * 10.0),
            )
        if name == "TAIL_RISK":
            return replace_input(
                base_input,
                liquidity_index=add_index(base_input.liquidity_index, -self.config.extreme_shock_std * 10.0),
                leading_diffusion_index=add_ldi(base_input.leading_diffusion_index, -0.60),
                hhi_concentration_score=add_probability(base_input.hhi_concentration_score, 0.25),
                volatility_index=add_index(base_input.volatility_index, self.config.extreme_shock_std * 10.0),
                regime_probability=add_probability(base_input.regime_probability, 0.35),
            )
        if name == "LIQUIDITY_SHOCK":
            return replace_input(
                base_input,
                liquidity_index=add_index(base_input.liquidity_index, -self.config.severe_shock_std * 10.0),
                liquidity_transmission_score=add_index(base_input.liquidity_transmission_score, -self.config.moderate_shock_std * 10.0),
            )
        if name == "INDIA_STRESS":
            return replace_input(
                base_input,
                leading_diffusion_index=add_ldi(base_input.leading_diffusion_index, -0.35),
                hhi_concentration_score=add_probability(base_input.hhi_concentration_score, 0.20),
                regime_probability=add_probability(base_input.regime_probability, 0.20),
            )
        if name == "CRYPTO_CRISIS":
            return replace_input(
                base_input,
                crypto_liquidity_index=add_index(base_input.crypto_liquidity_index, -self.config.extreme_shock_std * 10.0),
                volatility_index=add_index(base_input.volatility_index, self.config.severe_shock_std * 10.0),
            )
        raise ValueError(f"Unsupported scenario: {scenario_name}")

    def scenario_novelty_score(
        self,
        scenario_input: AggregatorInput,
        historical_inputs: Sequence[AggregatorInput],
    ) -> float:
        if not historical_inputs:
            return 0.0
        target = feature_vector(scenario_input)
        history = [feature_vector(item) for item in historical_inputs]
        center = [mean(column) for column in zip(*history)]
        spreads = [pstdev(column) or 1.0 for column in zip(*history)]
        distance = math.sqrt(sum(((value - avg) / spread) ** 2 for value, avg, spread in zip(target, center, spreads)))
        return round(clamp(distance / self.config.max_mahalanobis * 100.0, 0.0, 100.0), 6)

    def transition_matrix(self, scenarios: Sequence[ScenarioResult]) -> dict[str, dict[str, float]]:
        if not scenarios:
            return {state: uniform_transition_row() for state in REGIME_STATES}
        systemic = mean(
            scenario.probability_matrix.probabilities["systemic_stress"][12]
            for scenario in scenarios
        )
        row = transition_row_from_systemic(systemic)
        return {state: dict(row) for state in REGIME_STATES}

    def counterfactual_paths(self, base_input: AggregatorInput) -> list[CounterfactualPath]:
        base_matrix = self.probability_aggregator.aggregate(base_input)
        base_risk = base_matrix.probabilities["systemic_stress"][12]
        candidates = [
            ("increase_liquidity", replace_input(base_input, liquidity_index=add_index(base_input.liquidity_index, self.config.action_step))),
            ("improve_breadth", replace_input(base_input, leading_diffusion_index=add_ldi(base_input.leading_diffusion_index, 0.20))),
            ("reduce_concentration", replace_input(base_input, hhi_concentration_score=add_probability(base_input.hhi_concentration_score, -0.15))),
            ("lower_volatility", replace_input(base_input, volatility_index=add_index(base_input.volatility_index, -self.config.action_step))),
            ("improve_crypto_liquidity", replace_input(base_input, crypto_liquidity_index=add_index(base_input.crypto_liquidity_index, self.config.action_step))),
            ("stabilize_regime", replace_input(base_input, regime_probability=add_probability(base_input.regime_probability, -0.20))),
        ]
        paths: list[CounterfactualPath] = []
        for action, adjusted in candidates:
            matrix = self.probability_aggregator.aggregate(adjusted)
            risk = matrix.probabilities["systemic_stress"][12]
            paths.append(
                CounterfactualPath(
                    action_name=action,
                    adjusted_input=adjusted,
                    systemic_stress_12m=round(risk, 6),
                    risk_reduction=round(max(0.0, base_risk - risk), 6),
                )
            )
        paths.sort(key=lambda item: (item.risk_reduction, -item.systemic_stress_12m), reverse=True)
        return paths[: self.config.counterfactual_top_k]


def load_threshold_config(config_path: Path | None = None) -> ScenarioConfig:
    path = config_path or Path(__file__).resolve().parents[2] / "config" / "thresholds_config.yaml"
    data = parse_simple_yaml(path.read_text(encoding="utf-8"))
    shocks = data.get("shock_std_bounds", {})
    counterfactual = data.get("counterfactual", {})
    novelty = data.get("novelty", {})
    return ScenarioConfig(
        mild_shock_std=float(shocks.get("mild", 0.5)),
        moderate_shock_std=float(shocks.get("moderate", 1.0)),
        severe_shock_std=float(shocks.get("severe", 2.0)),
        extreme_shock_std=float(shocks.get("extreme", 3.0)),
        counterfactual_top_k=int(counterfactual.get("top_k", 5)),
        action_step=float(counterfactual.get("action_step", 10.0)),
        max_mahalanobis=float(novelty.get("max_mahalanobis", 6.0)),
    )


def parse_simple_yaml(raw: str) -> dict[str, dict[str, float]]:
    parsed: dict[str, dict[str, float]] = {}
    current: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.endswith(":"):
            current = stripped[:-1]
            parsed[current] = {}
            continue
        if current and ":" in stripped:
            key, value = stripped.split(":", 1)
            parsed[current][key] = float(value.strip())
    return parsed


def replace_input(base: AggregatorInput, **updates: float | None) -> AggregatorInput:
    values = {
        "timestamp": base.timestamp,
        "liquidity_index": base.liquidity_index,
        "liquidity_transmission_score": base.liquidity_transmission_score,
        "leading_diffusion_index": base.leading_diffusion_index,
        "hhi_concentration_score": base.hhi_concentration_score,
        "discovery_score": base.discovery_score,
        "backtest_sharpe": base.backtest_sharpe,
        "backtest_win_rate": base.backtest_win_rate,
        "regime_probability": base.regime_probability,
        "volatility_index": base.volatility_index,
        "crypto_liquidity_index": base.crypto_liquidity_index,
        "previous_systemic_stress_12m": base.previous_systemic_stress_12m,
    }
    values.update(updates)
    return AggregatorInput(**values)


def feature_vector(input_data: AggregatorInput) -> list[float]:
    return [
        clean_index(input_data.liquidity_index) / 100.0,
        clean_index(input_data.liquidity_transmission_score) / 100.0,
        clamp(input_data.leading_diffusion_index if input_data.leading_diffusion_index is not None else 0.0, -1.0, 1.0),
        clean_probability(input_data.hhi_concentration_score, 0.25),
        clean_index(input_data.discovery_score) / 100.0,
        clean_probability(input_data.regime_probability, 0.5),
        clean_index(input_data.volatility_index, default=30.0) / 100.0,
        clean_index(input_data.crypto_liquidity_index) / 100.0,
    ]


def transition_row_from_systemic(systemic_probability: float) -> dict[str, float]:
    risk = clamp(systemic_probability, 0.0, 1.0)
    raw = {
        "LOW_RISK": max(0.01, 1.0 - risk * 1.4),
        "WATCH": max(0.01, 0.30 - abs(risk - 0.30) * 0.35),
        "ELEVATED": max(0.01, 0.35 - abs(risk - 0.50) * 0.30),
        "HIGH_RISK": max(0.01, risk * 0.65),
        "CRISIS": max(0.01, risk * risk),
    }
    total = sum(raw.values())
    return {state: round(value / total, 10) for state, value in raw.items()}


def uniform_transition_row() -> dict[str, float]:
    return {state: 1.0 / len(REGIME_STATES) for state in REGIME_STATES}


def add_index(value: float | None, delta: float) -> float:
    return clamp(clean_index(value) + delta, 0.0, 100.0)


def add_probability(value: float | None, delta: float) -> float:
    return clamp(clean_probability(value, 0.5) + delta, 0.0, 1.0)


def add_ldi(value: float | None, delta: float) -> float:
    return clamp((0.0 if value is None else float(value)) + delta, -1.0, 1.0)


def clean_index(value: float | None, *, default: float = 50.0) -> float:
    return clamp(default if value is None else float(value), 0.0, 100.0)


def clean_probability(value: float | None, default: float) -> float:
    return clamp(default if value is None else float(value), 0.0, 1.0)
