"""Immutable calibration/holdout run split for Task 4B-7."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Tuple

from .v1_twin_schema import (
    SCHEMA_VERSION,
    V1CalibrationSet,
    V1HoldoutSet,
    assert_disjoint,
)


class V1RunSplitError(ValueError):
    """Raised when run-id isolation or manifest validation fails."""


def _normalize_run_ids(values: Iterable[Any], field_name: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise V1RunSplitError("{} must be an iterable of run IDs".format(field_name))
    try:
        normalized = frozenset(values)
    except TypeError as exc:
        raise V1RunSplitError("{} must be an iterable of run IDs".format(field_name)) from exc
    if any(not isinstance(run_id, str) or not run_id for run_id in normalized):
        raise V1RunSplitError("{} must contain non-empty string run IDs".format(field_name))
    return normalized


@dataclass(frozen=True)
class V1RunSplit:
    """Immutable run-id split; holdout starts empty by construction."""

    calibration_run_ids: frozenset[str]
    holdout_run_ids: frozenset[str] = frozenset()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        calibration = _normalize_run_ids(self.calibration_run_ids, "calibration_run_ids")
        holdout = _normalize_run_ids(self.holdout_run_ids, "holdout_run_ids")
        if not calibration:
            raise V1RunSplitError("calibration_run_ids must not be empty")
        if calibration & holdout:
            overlap = ", ".join(sorted(calibration & holdout))
            raise V1RunSplitError("calibration/holdout overlap: {}".format(overlap))
        if not isinstance(self.schema_version, str) or not self.schema_version:
            raise V1RunSplitError("schema_version must be non-empty")
        object.__setattr__(self, "calibration_run_ids", calibration)
        object.__setattr__(self, "holdout_run_ids", holdout)

        # Reuse the schema-level hard check so this boundary cannot drift from
        # the core V1 contract used by later validators.
        assert_disjoint(
            V1CalibrationSet(calibration, schema_version=self.schema_version),
            V1HoldoutSet(holdout, schema_version=self.schema_version),
        )

    @classmethod
    def from_run_ids(
        cls,
        calibration_run_ids: Iterable[Any],
        holdout_run_ids: Iterable[Any] = (),
        *,
        schema_version: str = SCHEMA_VERSION,
    ) -> "V1RunSplit":
        return cls(
            # Keep raw iterables until __post_init__ so strings are rejected
            # as a collection instead of being silently split into characters.
            calibration_run_ids=calibration_run_ids,  # type: ignore[arg-type]
            holdout_run_ids=holdout_run_ids,  # type: ignore[arg-type]
            schema_version=schema_version,
        )

    @property
    def calibration_set(self) -> V1CalibrationSet:
        return V1CalibrationSet(self.calibration_run_ids, self.schema_version)

    @property
    def holdout_set(self) -> V1HoldoutSet:
        return V1HoldoutSet(self.holdout_run_ids, self.schema_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "V1RunSplit",
            "calibration_run_ids": sorted(self.calibration_run_ids),
            "holdout_run_ids": sorted(self.holdout_run_ids),
            "schema_version": self.schema_version,
        }
