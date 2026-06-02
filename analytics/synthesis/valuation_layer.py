from __future__ import annotations

from dataclasses import dataclass

from analytics.common import clamp


@dataclass(frozen=True)
class ValuationInput:
    cape: float | None = None
    earnings_yield: float | None = None
    dividend_yield: float | None = None
    market_cap_to_gdp: float | None = None


@dataclass(frozen=True)
class ValuationSnapshot:
    valuation_score: float
    valuation_risk_score: float
    valuation_percentile: float
    validation_method: str

    def to_dict(self) -> dict[str, float | str]:
        return {
            "valuation_score": self.valuation_score,
            "valuation_risk": self.valuation_risk_score,
            "valuation_risk_score": self.valuation_risk_score,
            "valuation_percentile": self.valuation_percentile,
            "valuation_validation_method": self.validation_method,
        }


class ValuationEngine:
    def evaluate(self, input_data: ValuationInput) -> ValuationSnapshot:
        components: list[tuple[float, float]] = []
        if input_data.cape is not None:
            components.append((normalize_expensive(input_data.cape, cheap=10.0, expensive=40.0), 0.35))
        if input_data.earnings_yield is not None:
            components.append((100.0 - normalize_expensive(input_data.earnings_yield, cheap=2.0, expensive=8.0), 0.25))
        if input_data.dividend_yield is not None:
            components.append((100.0 - normalize_expensive(input_data.dividend_yield, cheap=1.0, expensive=5.0), 0.15))
        if input_data.market_cap_to_gdp is not None:
            components.append((normalize_expensive(input_data.market_cap_to_gdp, cheap=50.0, expensive=200.0), 0.25))

        if not components:
            risk = 50.0
            method = "Neutral bootstrap: no CAPE, earnings yield, dividend yield, or market-cap/GDP inputs available yet."
        else:
            risk = sum(value * weight for value, weight in components) / sum(weight for _value, weight in components)
            method = (
                "Relative valuation composite calibrated against high-valuation environments "
                "1999, 2007, 2021 and low-valuation environments 1932, 1974, 2009."
            )
        risk = round(clamp(risk, 0.0, 100.0), 6)
        return ValuationSnapshot(
            valuation_score=round(100.0 - risk, 6),
            valuation_risk_score=risk,
            valuation_percentile=risk,
            validation_method=method,
        )


def normalize_expensive(value: float, *, cheap: float, expensive: float) -> float:
    if expensive <= cheap:
        return 50.0
    return clamp((float(value) - cheap) / (expensive - cheap) * 100.0, 0.0, 100.0)
