"""Offline contracts for 4B-7 calibration/holdout run isolation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from v1_twin.v1_twin_calibration_set import (
    V1RunSplit,
    V1RunSplitError,
)


def test_run_split_is_immutable_and_starts_without_holdout_runs():
    split = V1RunSplit.from_run_ids(("cal-01", "cal-02"))

    assert split.calibration_run_ids == frozenset(("cal-01", "cal-02"))
    assert split.holdout_run_ids == frozenset()
    with pytest.raises(FrozenInstanceError):
        split.calibration_run_ids = frozenset(("changed",))  # type: ignore[misc]


def test_calibration_and_holdout_overlap_is_rejected():
    with pytest.raises(V1RunSplitError, match="overlap"):
        V1RunSplit.from_run_ids(("run-1", "run-2"), ("run-2", "holdout-1"))


def test_run_ids_are_normalized_and_empty_calibration_is_rejected():
    split = V1RunSplit.from_run_ids(["run-2", "run-1", "run-1"])
    assert split.calibration_run_ids == frozenset(("run-1", "run-2"))

    with pytest.raises(V1RunSplitError, match="calibration"):
        V1RunSplit.from_run_ids(())

    with pytest.raises(V1RunSplitError, match="iterable"):
        V1RunSplit.from_run_ids("not-a-run-list")
