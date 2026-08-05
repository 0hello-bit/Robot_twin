"""Offline contracts for 4B-7 model freezing and holdout qualification."""

from __future__ import annotations

import pytest

from v1_twin.v1_twin_model_registry import (
    V1ModelFreezeError,
    V1ModelInvalidatedError,
    V1ModelRegistry,
)


PARAMETERS = {"wheel_gains": [1.0, 1.1, 0.9, 1.0], "body_bias": [0.0, 0.0, 0.0]}
STOP_CONDITIONS = {"max_duration_s": 20, "line_loss_ms": 300}


def test_holdout_cannot_be_registered_before_model_freeze():
    registry = V1ModelRegistry(("cal-01", "cal-02"))

    assert registry.is_frozen is False
    assert registry.holdout_run_ids == frozenset()
    with pytest.raises(V1ModelFreezeError, match="frozen"):
        registry.register_holdout("holdout-01")


def test_freeze_is_immutable_and_registers_new_holdout_runs_only_after_freeze():
    registry = V1ModelRegistry(("cal-01", "cal-02"))
    record = registry.freeze(
        model_version="plant-exploratory-1",
        parameters=PARAMETERS,
        code_hash="code-hash-1",
        stop_conditions=STOP_CONDITIONS,
        fit_timestamp_ns=123456789,
        fit_metadata={"iterations": 4, "converged": True},
    )

    assert registry.is_frozen is True
    assert record.model_hash
    assert record.fit_timestamp_ns == 123456789
    assert record.fit_metadata_json
    assert record.calibration_run_ids == frozenset(("cal-01", "cal-02"))
    assert registry.holdout_run_ids == frozenset()

    registry.register_holdout("holdout-01")
    assert registry.holdout_run_ids == frozenset(("holdout-01",))
    assert registry.holdout_is_valid is True

    with pytest.raises(V1ModelFreezeError, match="already frozen"):
        registry.freeze(
            model_version="plant-exploratory-2",
            parameters=PARAMETERS,
            code_hash="code-hash-2",
            stop_conditions=STOP_CONDITIONS,
        )
    with pytest.raises(V1ModelFreezeError, match="calibration"):
        registry.register_holdout("cal-01")
    with pytest.raises(V1ModelFreezeError, match="already registered"):
        registry.register_holdout("holdout-01")


def test_frozen_fingerprint_is_order_independent_but_changes_invalidate_holdout():
    registry = V1ModelRegistry(("cal-01",))
    registry.freeze(
        model_version="plant-exploratory-1",
        parameters={"b": 2, "a": 1},
        code_hash="code-hash-1",
        stop_conditions={"z": 3, "x": 4},
        fit_timestamp_ns=987654321,
        fit_metadata={"iterations": 9},
    )
    registry.register_holdout("holdout-01")

    assert registry.validate_frozen_inputs(
        parameters={"a": 1, "b": 2},
        code_hash="code-hash-1",
        stop_conditions={"x": 4, "z": 3},
    ) is True

    with pytest.raises(V1ModelInvalidatedError, match="changed"):
        registry.validate_frozen_inputs(
            parameters={"a": 1, "b": 99},
            code_hash="code-hash-1",
            stop_conditions={"x": 4, "z": 3},
        )
    assert registry.holdout_is_valid is False
    with pytest.raises(V1ModelFreezeError, match="invalid"):
        registry.register_holdout("holdout-02")


def test_registry_serialization_preserves_audit_fields():
    registry = V1ModelRegistry(("cal-01",))
    registry.freeze(
        model_version="plant-exploratory-1",
        parameters=PARAMETERS,
        code_hash="code-hash-1",
        stop_conditions=STOP_CONDITIONS,
        fit_timestamp_ns=123456789,
        fit_metadata={"iterations": 4, "converged": True},
    )
    registry.register_holdout("holdout-01")

    payload = registry.to_dict()

    assert payload["is_frozen"] is True
    assert payload["calibration_run_ids"] == ["cal-01"]
    assert payload["holdout_run_ids"] == ["holdout-01"]
    assert payload["model"]["model_version"] == "plant-exploratory-1"
    assert payload["model"]["model_hash"]
    assert payload["model"]["fit_timestamp_ns"] == 123456789
    assert payload["model"]["fit_metadata"] == {"converged": True, "iterations": 4}
