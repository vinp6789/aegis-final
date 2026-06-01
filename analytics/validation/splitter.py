from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence


@dataclass(frozen=True)
class TimeSeriesSplit:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    embargo_days: int

    @property
    def has_overlap(self) -> bool:
        return bool(set(self.train_indices).intersection(self.test_indices))


class WalkForwardSplitter:
    def __init__(
        self,
        *,
        train_size: int,
        test_size: int,
        step_size: int | None = None,
        embargo_days: int = 60,
        mode: str = "rolling",
    ) -> None:
        if train_size <= 0 or test_size <= 0:
            raise ValueError("train_size and test_size must be positive")
        if embargo_days < 0:
            raise ValueError("embargo_days must be non-negative")
        if mode not in {"rolling", "expanding"}:
            raise ValueError("mode must be 'rolling' or 'expanding'")
        self.train_size = train_size
        self.test_size = test_size
        self.step_size = step_size or test_size
        if self.step_size <= 0:
            raise ValueError("step_size must be positive")
        self.embargo_days = embargo_days
        self.mode = mode

    def split(self, timestamps: Sequence[datetime | date | str]) -> list[TimeSeriesSplit]:
        normalized = normalize_timestamps(timestamps)
        splits: list[TimeSeriesSplit] = []
        train_start_index = 0
        train_end_index = self.train_size

        while train_end_index <= len(normalized):
            train_end_time = normalized[train_end_index - 1]
            min_test_start_time = train_end_time + timedelta(days=self.embargo_days)
            test_start_index = first_index_at_or_after(normalized, min_test_start_time, train_end_index)
            test_end_index = test_start_index + self.test_size
            if test_end_index > len(normalized):
                break

            current_train_start = 0 if self.mode == "expanding" else train_start_index
            split = TimeSeriesSplit(
                train_indices=tuple(range(current_train_start, train_end_index)),
                test_indices=tuple(range(test_start_index, test_end_index)),
                train_start=normalized[current_train_start],
                train_end=train_end_time,
                test_start=normalized[test_start_index],
                test_end=normalized[test_end_index - 1],
                embargo_days=self.embargo_days,
            )
            validate_no_overlap(split)
            splits.append(split)

            if self.mode == "expanding":
                train_end_index += self.step_size
            else:
                train_start_index += self.step_size
                train_end_index = train_start_index + self.train_size

        return splits


class PurgedEmbargoedKFoldSplitter:
    def __init__(self, *, n_splits: int, embargo_days: int = 60) -> None:
        if n_splits < 2:
            raise ValueError("n_splits must be at least 2")
        if embargo_days < 0:
            raise ValueError("embargo_days must be non-negative")
        self.n_splits = n_splits
        self.embargo_days = embargo_days

    def split(self, timestamps: Sequence[datetime | date | str]) -> list[TimeSeriesSplit]:
        normalized = normalize_timestamps(timestamps)
        fold_bounds = fold_boundaries(len(normalized), self.n_splits)
        splits: list[TimeSeriesSplit] = []
        for test_start_index, test_end_index in fold_bounds:
            test_start = normalized[test_start_index]
            test_end = normalized[test_end_index - 1]
            purge_start = test_start - timedelta(days=self.embargo_days)
            embargo_end = test_end + timedelta(days=self.embargo_days)
            train_indices = tuple(
                index
                for index, timestamp in enumerate(normalized)
                if timestamp < purge_start or timestamp > embargo_end
            )
            if not train_indices:
                continue
            split = TimeSeriesSplit(
                train_indices=train_indices,
                test_indices=tuple(range(test_start_index, test_end_index)),
                train_start=normalized[train_indices[0]],
                train_end=normalized[train_indices[-1]],
                test_start=test_start,
                test_end=test_end,
                embargo_days=self.embargo_days,
            )
            if split.has_overlap:
                raise ValueError("training and testing indices overlap")
            splits.append(split)
        return splits


def rolling_walk_forward_split(
    timestamps: Sequence[datetime | date | str],
    *,
    train_size: int,
    test_size: int,
    step_size: int | None = None,
    embargo_days: int = 60,
) -> list[TimeSeriesSplit]:
    return WalkForwardSplitter(
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        embargo_days=embargo_days,
        mode="rolling",
    ).split(timestamps)


def expanding_walk_forward_split(
    timestamps: Sequence[datetime | date | str],
    *,
    train_size: int,
    test_size: int,
    step_size: int | None = None,
    embargo_days: int = 60,
) -> list[TimeSeriesSplit]:
    return WalkForwardSplitter(
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        embargo_days=embargo_days,
        mode="expanding",
    ).split(timestamps)


def combinatorial_purged_cv_paths(
    timestamps: Sequence[datetime | date | str],
    *,
    n_splits: int,
    embargo_days: int = 60,
) -> list[TimeSeriesSplit]:
    return PurgedEmbargoedKFoldSplitter(
        n_splits=n_splits,
        embargo_days=embargo_days,
    ).split(timestamps)


def validate_no_overlap(split: TimeSeriesSplit) -> None:
    if split.has_overlap:
        raise ValueError("training and testing indices overlap")
    min_test_start = split.train_end + timedelta(days=split.embargo_days)
    if split.test_start < min_test_start:
        raise ValueError("test window violates embargo period")


def normalize_timestamps(timestamps: Sequence[datetime | date | str]) -> list[datetime]:
    normalized: list[datetime] = []
    for value in timestamps:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime(value.year, value.month, value.day)
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value)
        else:
            raise ValueError(f"Unsupported timestamp value: {value!r}")
        normalized.append(parsed)
    if normalized != sorted(normalized):
        raise ValueError("timestamps must be sorted ascending")
    return normalized


def first_index_at_or_after(
    timestamps: Sequence[datetime],
    threshold: datetime,
    start_index: int,
) -> int:
    for index in range(start_index, len(timestamps)):
        if timestamps[index] >= threshold:
            return index
    return len(timestamps)


def fold_boundaries(total_observations: int, n_splits: int) -> list[tuple[int, int]]:
    if total_observations < n_splits:
        raise ValueError("total_observations must be at least n_splits")
    base_size = total_observations // n_splits
    remainder = total_observations % n_splits
    bounds: list[tuple[int, int]] = []
    start = 0
    for fold in range(n_splits):
        size = base_size + (1 if fold < remainder else 0)
        end = start + size
        bounds.append((start, end))
        start = end
    return bounds
