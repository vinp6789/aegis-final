from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Sequence


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def clip_probability(value: float | int | None, *, default: float = 0.5) -> float:
    if value is None:
        return default
    if math.isnan(float(value)):
        return default
    return clamp(float(value), 0.0, 1.0)


def normalize_to_100(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    finite = [float(value) for value in values]
    low = min(finite)
    high = max(finite)
    if high == low:
        return [50.0 for _value in finite]
    return [round(clamp((value - low) / (high - low) * 100.0, 0.0, 100.0), 6) for value in finite]


def normalize_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
