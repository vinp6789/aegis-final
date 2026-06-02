from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean
from typing import Callable, Mapping, Sequence

from analytics.common import clamp


@dataclass(frozen=True)
class CrisisPeriod:
    crisis_name: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class ReplayObservation:
    timestamp: datetime
    panic_probability: float
    recovery_probability: float
    buy_score: float
    sell_score: float
    expected_return: float
    expected_drawdown: float
    realized_return: float | None = None
    realized_drawdown: float | None = None


@dataclass(frozen=True)
class CrisisReplayResult:
    crisis_detection_rate: float
    crisis_similarity_score: float
    crisis_replay_score: float
    panic_false_positive_rate: float
    recovery_detection_rate: float
    drawdown_reduction_score: float
    signal_quality_score: float
    crisis_lead_time_months: float
    panic_lead_time_months: float
    recovery_lead_time_months: float
    validation_method: str

    def to_dict(self) -> dict[str, float | str]:
        return {
            "crisis_detection_rate": self.crisis_detection_rate,
            "crisis_similarity_score": self.crisis_similarity_score,
            "crisis_replay_score": self.crisis_replay_score,
            "panic_false_positive_rate": self.panic_false_positive_rate,
            "recovery_detection_rate": self.recovery_detection_rate,
            "drawdown_reduction_score": self.drawdown_reduction_score,
            "signal_quality_score": self.signal_quality_score,
            "crisis_lead_time_months": self.crisis_lead_time_months,
            "panic_lead_time_months": self.panic_lead_time_months,
            "recovery_lead_time_months": self.recovery_lead_time_months,
            "crisis_replay_validation_method": self.validation_method,
        }


CRISIS_LIBRARY = (
    CrisisPeriod("1929 Great Crash", date(1929, 9, 1), date(1932, 7, 31)),
    CrisisPeriod("1973 Inflation Shock", date(1973, 1, 1), date(1974, 12, 31)),
    CrisisPeriod("1987 Crash", date(1987, 8, 1), date(1987, 12, 31)),
    CrisisPeriod("2000-2002 Dotcom Crash", date(2000, 3, 1), date(2002, 10, 31)),
    CrisisPeriod("2007-2009 Global Financial Crisis", date(2007, 10, 1), date(2009, 3, 31)),
    CrisisPeriod("2020 Pandemic Shock", date(2020, 2, 1), date(2020, 4, 30)),
)


class CrisisReplayEngine:
    def replay(self, observations_by_crisis: Mapping[str, Sequence[ReplayObservation]]) -> CrisisReplayResult:
        if not observations_by_crisis:
            return neutral_result("Neutral bootstrap: no historical crisis replay observations available yet.")

        detection_scores = []
        false_positive_scores = []
        recovery_scores = []
        drawdown_scores = []
        signal_quality_scores = []
        panic_leads = []
        recovery_leads = []

        for crisis in CRISIS_LIBRARY:
            observations = list(observations_by_crisis.get(crisis.crisis_name, ()))
            if not observations:
                continue
            crisis_obs = [item for item in observations if crisis.start_date <= item.timestamp.date() <= crisis.end_date]
            pre_obs = [item for item in observations if item.timestamp.date() < crisis.start_date]
            post_obs = [item for item in observations if item.timestamp.date() > crisis.end_date]
            detection_scores.append(any_score(crisis_obs, lambda item: item.panic_probability >= 60.0))
            false_positive_scores.extend(
                1.0 if item.panic_probability >= 60.0 else 0.0
                for item in pre_obs + post_obs
            )
            recovery_scores.append(any_score(post_obs or crisis_obs, lambda item: item.recovery_probability >= 60.0))
            drawdown_scores.extend(drawdown_reduction(item) for item in crisis_obs)
            signal_quality_scores.extend(signal_quality(item) for item in observations)
            panic_leads.append(lead_time_months(pre_obs + crisis_obs, crisis.start_date, "panic"))
            recovery_leads.append(lead_time_months(crisis_obs + post_obs, crisis.end_date, "recovery"))

        if not detection_scores:
            return neutral_result("Neutral bootstrap: crisis periods exist, but no matched historical observations are available.")

        return CrisisReplayResult(
            crisis_detection_rate=percent(detection_scores, neutral=50.0),
            crisis_similarity_score=percent(detection_scores, neutral=50.0),
            crisis_replay_score=percent(signal_quality_scores, neutral=50.0),
            panic_false_positive_rate=percent(false_positive_scores, neutral=0.0),
            recovery_detection_rate=percent(recovery_scores, neutral=50.0),
            drawdown_reduction_score=percent(drawdown_scores, neutral=50.0),
            signal_quality_score=percent(signal_quality_scores, neutral=50.0),
            crisis_lead_time_months=round(mean_or_default([value for value in panic_leads if value is not None], 0.0), 6),
            panic_lead_time_months=round(mean_or_default([value for value in panic_leads if value is not None], 0.0), 6),
            recovery_lead_time_months=round(mean_or_default([value for value in recovery_leads if value is not None], 0.0), 6),
            validation_method=(
                "Replays stored Aegis forecast_history snapshots across 1929, 1973, 1987, 2000, 2008, and 2020 crisis windows; "
                "uses existing daily_market_metrics realized returns/drawdowns when available."
            ),
        )


def neutral_result(method: str) -> CrisisReplayResult:
    return CrisisReplayResult(
        crisis_detection_rate=50.0,
        crisis_similarity_score=50.0,
        crisis_replay_score=50.0,
        panic_false_positive_rate=0.0,
        recovery_detection_rate=50.0,
        drawdown_reduction_score=50.0,
        signal_quality_score=50.0,
        crisis_lead_time_months=0.0,
        panic_lead_time_months=0.0,
        recovery_lead_time_months=0.0,
        validation_method=method,
    )


def any_score(observations: Sequence[ReplayObservation], predicate: Callable[[ReplayObservation], bool]) -> float:
    if not observations:
        return 0.0
    return 1.0 if any(predicate(item) for item in observations) else 0.0


def drawdown_reduction(observation: ReplayObservation) -> float:
    if observation.realized_drawdown is None:
        return 0.5
    protection = observation.sell_score / 100.0
    drawdown = clamp(observation.realized_drawdown, 0.0, 1.0)
    return clamp(0.5 + protection * drawdown - max(0.0, observation.buy_score - observation.sell_score) / 100.0 * drawdown, 0.0, 1.0)


def signal_quality(observation: ReplayObservation) -> float:
    realized_return = observation.realized_return
    if realized_return is None:
        return 0.5
    panic_alignment = 1.0 - abs(observation.panic_probability / 100.0 - (1.0 if realized_return < -0.08 else 0.0))
    recovery_alignment = 1.0 - abs(observation.recovery_probability / 100.0 - (1.0 if realized_return > 0.05 else 0.0))
    return clamp((panic_alignment + recovery_alignment) / 2.0, 0.0, 1.0)


def lead_time_months(observations: Sequence[ReplayObservation], anchor: date, mode: str) -> float | None:
    threshold = 60.0
    candidates = []
    for item in observations:
        value = item.panic_probability if mode == "panic" else item.recovery_probability
        if value >= threshold:
            delta_days = (anchor - item.timestamp.date()).days if mode == "panic" else (item.timestamp.date() - anchor).days
            if delta_days >= 0:
                candidates.append(delta_days / 30.0)
    return max(candidates) if candidates else None


def percent(values: Sequence[float], *, neutral: float) -> float:
    if not values:
        return neutral
    return round(clamp(mean(values) * 100.0, 0.0, 100.0), 6)


def mean_or_default(values: Sequence[float], default: float) -> float:
    return mean(values) if values else default
