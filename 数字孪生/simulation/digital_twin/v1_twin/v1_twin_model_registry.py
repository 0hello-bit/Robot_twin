"""Auditable model freeze and holdout registry for Task 4B-7.

The registry is intentionally small and mutable only through explicit methods.
After ``freeze`` the model fingerprint cannot be replaced.  If a caller later
proposes different parameters, code identity, or stopping conditions, the
existing holdout qualification is invalidated rather than silently reused.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from .v1_twin_calibration_set import V1RunSplit, V1RunSplitError
from .v1_twin_schema import SCHEMA_VERSION


class V1ModelFreezeError(RuntimeError):
    """Raised when a freeze/holdout operation violates the registry state."""


class V1ModelInvalidatedError(V1ModelFreezeError):
    """Raised when frozen inputs differ from the registered fingerprint."""


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError("value is not JSON serializable: {}".format(type(value).__name__))


def _canonical_json(value: Any, field_name: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
    except (TypeError, ValueError) as exc:
        raise V1ModelFreezeError("{} must be JSON serializable".format(field_name)) from exc


@dataclass(frozen=True)
class V1FrozenModelRecord:
    model_version: str
    parameters_json: str
    code_hash: str
    stop_conditions_json: str
    calibration_run_ids: frozenset[str]
    model_hash: str
    fit_timestamp_ns: int
    fit_metadata_json: str
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "parameters": json.loads(self.parameters_json),
            "code_hash": self.code_hash,
            "stop_conditions": json.loads(self.stop_conditions_json),
            "calibration_run_ids": sorted(self.calibration_run_ids),
            "model_hash": self.model_hash,
            "fit_timestamp_ns": self.fit_timestamp_ns,
            "fit_metadata": json.loads(self.fit_metadata_json),
            "schema_version": self.schema_version,
        }


class V1ModelRegistry:
    """Mutable registry with a one-way model-freeze transition."""

    def __init__(self, calibration_run_ids, *, schema_version: str = SCHEMA_VERSION) -> None:
        try:
            self._split = V1RunSplit.from_run_ids(
                calibration_run_ids,
                schema_version=schema_version,
            )
        except V1RunSplitError as exc:
            raise V1ModelFreezeError(str(exc)) from exc
        self._model: V1FrozenModelRecord | None = None
        self._holdout_run_ids: set[str] = set()
        self._holdout_is_valid = True

    @property
    def is_frozen(self) -> bool:
        return self._model is not None

    @property
    def calibration_run_ids(self) -> frozenset[str]:
        return self._split.calibration_run_ids

    @property
    def holdout_run_ids(self) -> frozenset[str]:
        return frozenset(self._holdout_run_ids)

    @property
    def frozen_model(self) -> V1FrozenModelRecord | None:
        return self._model

    @property
    def holdout_is_valid(self) -> bool:
        return self._holdout_is_valid

    def freeze(
        self,
        *,
        model_version: str,
        parameters: Any,
        code_hash: str,
        stop_conditions: Any,
        fit_timestamp_ns: int | None = None,
        fit_metadata: Any = None,
    ) -> V1FrozenModelRecord:
        if self.is_frozen:
            raise V1ModelFreezeError("model is already frozen")
        if not isinstance(model_version, str) or not model_version:
            raise V1ModelFreezeError("model_version must be non-empty")
        if not isinstance(code_hash, str) or not code_hash:
            raise V1ModelFreezeError("code_hash must be non-empty")
        parameters_json = _canonical_json(parameters, "parameters")
        stop_conditions_json = _canonical_json(stop_conditions, "stop_conditions")
        if fit_timestamp_ns is None:
            fit_timestamp_ns = time.time_ns()
        if isinstance(fit_timestamp_ns, bool) or not isinstance(fit_timestamp_ns, int):
            raise V1ModelFreezeError("fit_timestamp_ns must be an int")
        if fit_timestamp_ns < 0:
            raise V1ModelFreezeError("fit_timestamp_ns must be >= 0")
        fit_metadata_json = _canonical_json(
            {} if fit_metadata is None else fit_metadata,
            "fit_metadata",
        )
        fingerprint_payload = {
            "model_version": model_version,
            "parameters": json.loads(parameters_json),
            "code_hash": code_hash,
            "stop_conditions": json.loads(stop_conditions_json),
            "calibration_run_ids": sorted(self.calibration_run_ids),
            "schema_version": self._split.schema_version,
        }
        model_hash = hashlib.sha256(
            _canonical_json(fingerprint_payload, "model fingerprint").encode("utf-8")
        ).hexdigest()
        self._model = V1FrozenModelRecord(
            model_version=model_version,
            parameters_json=parameters_json,
            code_hash=code_hash,
            stop_conditions_json=stop_conditions_json,
            calibration_run_ids=self.calibration_run_ids,
            model_hash=model_hash,
            fit_timestamp_ns=fit_timestamp_ns,
            fit_metadata_json=fit_metadata_json,
            schema_version=self._split.schema_version,
        )
        self._holdout_is_valid = True
        return self._model

    def register_holdout(self, run_id: str) -> None:
        if not self.is_frozen:
            raise V1ModelFreezeError("model must be frozen before registering holdout")
        if not self._holdout_is_valid:
            raise V1ModelFreezeError("holdout qualification is invalid after frozen inputs changed")
        if not isinstance(run_id, str) or not run_id:
            raise V1ModelFreezeError("holdout run_id must be a non-empty string")
        if run_id in self.calibration_run_ids:
            raise V1ModelFreezeError("holdout run_id overlaps calibration")
        if run_id in self._holdout_run_ids:
            raise V1ModelFreezeError("holdout run_id is already registered")
        self._holdout_run_ids.add(run_id)

    def validate_frozen_inputs(
        self,
        *,
        parameters: Any,
        code_hash: str,
        stop_conditions: Any,
    ) -> bool:
        """Check current inputs against the frozen fingerprint.

        A mismatch invalidates all holdout qualification and is intentionally
        terminal for this registry instance; callers must create a new registry
        and a new holdout set after refitting.
        """
        if not self.is_frozen or self._model is None:
            raise V1ModelFreezeError("model must be frozen before validation")
        parameters_json = _canonical_json(parameters, "parameters")
        stop_conditions_json = _canonical_json(stop_conditions, "stop_conditions")
        if (
            parameters_json != self._model.parameters_json
            or code_hash != self._model.code_hash
            or stop_conditions_json != self._model.stop_conditions_json
        ):
            self._holdout_is_valid = False
            raise V1ModelInvalidatedError("frozen model inputs changed")
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "V1ModelRegistry",
            "is_frozen": self.is_frozen,
            "calibration_run_ids": sorted(self.calibration_run_ids),
            "holdout_run_ids": sorted(self._holdout_run_ids),
            "holdout_is_valid": self.holdout_is_valid,
            "model": None if self._model is None else self._model.to_dict(),
            "schema_version": self._split.schema_version,
        }
