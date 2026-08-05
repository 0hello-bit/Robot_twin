"""Fail-closed readiness gates for the V1 digital twin.

The validator consumes already-produced evidence.  It never starts a camera,
transport, serial session, or model run, and it never treats missing evidence
as a pass.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Any, Dict, Tuple


PASS = "PASS"
FAIL = "FAIL"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
NOT_READY = "NOT_READY"
READY = "READY"
GATE_IDS = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("{} must be numeric".format(name))
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("{} must be finite".format(name))
    return number


def _bounded(value: object, name: str, lower: float, upper: float) -> float:
    number = _finite(value, name)
    if number < lower or number > upper:
        raise ValueError("{} must be in [{}, {}]".format(name, lower, upper))
    return number


def _count(value: object, name: str, *, positive: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("{} must be an integer".format(name))
    if (positive and value <= 0) or (not positive and value < 0):
        comparator = "> 0" if positive else ">= 0"
        raise ValueError("{} must be {}".format(name, comparator))
    return value


def _reason_from_exception(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    return None


@dataclass(frozen=True)
class V1GateResult:
    gate_id: str
    status: str
    measured: Dict[str, Any]
    thresholds: Dict[str, Any]
    reason: str = ""

    def __post_init__(self) -> None:
        if self.gate_id not in GATE_IDS:
            raise ValueError("unsupported gate_id")
        if self.status not in (PASS, FAIL, INSUFFICIENT_EVIDENCE):
            raise ValueError("unsupported gate status")
        if not isinstance(self.reason, str):
            raise ValueError("reason must be a string")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "status": self.status,
            "measured": dict(self.measured),
            "thresholds": dict(self.thresholds),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class V1ValidationReport:
    verdict: str
    gates: Dict[str, V1GateResult]
    data_isolation: Dict[str, Any]
    calibration_run_ids: Tuple[str, ...]
    holdout_run_ids: Tuple[str, ...]
    model_version: str | None

    def __post_init__(self) -> None:
        if self.verdict not in (READY, NOT_READY, INSUFFICIENT_EVIDENCE):
            raise ValueError("unsupported validation verdict")
        if tuple(self.gates) != GATE_IDS:
            raise ValueError("gates must contain G1 through G8 in order")
        if self.model_version is not None and not isinstance(self.model_version, str):
            raise ValueError("model_version must be a string or None")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "gates": {key: value.to_dict() for key, value in self.gates.items()},
            "data_isolation": dict(self.data_isolation),
            "calibration_run_ids": list(self.calibration_run_ids),
            "holdout_run_ids": list(self.holdout_run_ids),
            "model_version": self.model_version,
        }


class V1TwinValidator:
    """Evaluate G1-G8 without executing any external activity."""

    @classmethod
    def evaluate(
        cls,
        gate_evidence: Mapping[str, Mapping[str, object]] | None,
        holdout_evidence: Mapping[str, object] | None,
        *,
        calibration_run_ids: Iterable[str] = (),
        holdout_run_ids: Iterable[str] = (),
        model_version: str | None = None,
    ) -> V1ValidationReport:
        gate_source = _as_mapping(gate_evidence) or {}
        holdout_source = _as_mapping(holdout_evidence) or {}
        normalized_model_version, model_version_error = cls._normalize_model_version(model_version)
        gates = {
            "G1": cls._g1(gate_source.get("G1")),
            "G2": cls._g2(gate_source.get("G2")),
            "G3": cls._g3(gate_source.get("G3")),
            "G4": cls._g4(gate_source.get("G4")),
            "G5": cls._g5(holdout_source.get("g5")),
            "G6": cls._g6(holdout_source.get("g6")),
            "G7": cls._g7(holdout_source.get("g7")),
            "G8": cls._g8(holdout_source.get("g8")),
        }
        calibration, calibration_error = cls._normalize_ids(calibration_run_ids, "calibration")
        holdout, holdout_error = cls._normalize_ids(holdout_run_ids, "holdout")
        isolation = cls._isolation(
            calibration,
            holdout,
            calibration_error=calibration_error,
            holdout_error=holdout_error,
            model_version=normalized_model_version,
            model_version_error=model_version_error,
        )
        statuses = [result.status for result in gates.values()]
        statuses.append(isolation["status"])
        if FAIL in statuses:
            verdict = NOT_READY
        elif INSUFFICIENT_EVIDENCE in statuses:
            verdict = INSUFFICIENT_EVIDENCE
        else:
            verdict = READY
        return V1ValidationReport(
            verdict=verdict,
            gates=gates,
            data_isolation=isolation,
            calibration_run_ids=calibration,
            holdout_run_ids=holdout,
            model_version=normalized_model_version,
        )

    @staticmethod
    def _result(
        gate_id: str,
        status: str,
        measured: Mapping[str, Any],
        thresholds: Mapping[str, Any],
        reason: str = "",
    ) -> V1GateResult:
        return V1GateResult(
            gate_id=gate_id,
            status=status,
            measured=dict(measured),
            thresholds=dict(thresholds),
            reason=reason,
        )

    @classmethod
    def _evidence(
        cls,
        gate_id: str,
        evidence: object,
        keys: Sequence[str],
        thresholds: Mapping[str, Any],
    ) -> tuple[Mapping[str, object] | None, V1GateResult | None]:
        source = _as_mapping(evidence)
        if source is None:
            return None, cls._result(
                gate_id,
                INSUFFICIENT_EVIDENCE,
                {},
                thresholds,
                "evidence section is missing or not a mapping",
            )
        explicit_failure = None
        malformed_marker = None
        for marker_key in ("observed_failure", "failure"):
            if marker_key not in source:
                continue
            failure = source[marker_key]
            if isinstance(failure, bool):
                if failure:
                    explicit_failure = (marker_key, failure)
            elif isinstance(failure, str):
                if failure.strip():
                    explicit_failure = (marker_key, failure)
            else:
                malformed_marker = marker_key
        if explicit_failure is not None:
            marker_key, failure = explicit_failure
            return None, cls._result(
                gate_id,
                FAIL,
                {marker_key: failure},
                thresholds,
                "explicit observed failure: {}".format(failure),
            )
        if malformed_marker is not None:
            return None, cls._result(
                gate_id,
                INSUFFICIENT_EVIDENCE,
                {"malformed_failure_marker": malformed_marker},
                thresholds,
                "{} must be a bool or string".format(malformed_marker),
            )
        missing = [key for key in keys if key not in source]
        if missing:
            return None, cls._result(
                gate_id,
                INSUFFICIENT_EVIDENCE,
                {},
                thresholds,
                "missing evidence: {}".format(", ".join(missing)),
            )
        return source, None

    @classmethod
    def _g1(cls, evidence: object) -> V1GateResult:
        thresholds = {"fps_min": 20.0, "drop_rate_max": 0.05, "timestamps_monotonic": True, "invalid_frames": 0}
        source, early = cls._evidence(
            "G1", evidence, ("fps", "drop_rate", "timestamps_monotonic", "invalid_frames"), thresholds
        )
        if early:
            return early
        assert source is not None
        try:
            fps = _finite(source["fps"], "fps")
            if fps < 0.0:
                raise ValueError("fps must be >= 0")
            drop = _bounded(source["drop_rate"], "drop_rate", 0.0, 1.0)
            monotonic = source["timestamps_monotonic"]
            invalid = _count(source["invalid_frames"], "invalid_frames", positive=False)
            if not isinstance(monotonic, bool):
                raise ValueError("timestamps_monotonic must be a bool")
        except (TypeError, ValueError) as exc:
            return cls._result("G1", INSUFFICIENT_EVIDENCE, {}, thresholds, _reason_from_exception(exc))
        measured = {"fps": fps, "drop_rate": drop, "timestamps_monotonic": monotonic, "invalid_frames": invalid}
        failures = []
        if fps < 20.0:
            failures.append("fps below 20")
        if drop > 0.05:
            failures.append("drop_rate above 0.05")
        if not monotonic:
            failures.append("timestamps are not monotonic")
        if invalid != 0:
            failures.append("invalid_frames is nonzero")
        return cls._result("G1", FAIL if failures else PASS, measured, thresholds, "; ".join(failures))

    @classmethod
    def _g2(cls, evidence: object) -> V1GateResult:
        source, early = cls._evidence("G2", evidence, ("reprojection_p95_px", "black_line_width_px"), {})
        if early:
            return early
        assert source is not None
        try:
            reprojection = _finite(source["reprojection_p95_px"], "reprojection_p95_px")
            width = _finite(source["black_line_width_px"], "black_line_width_px")
            if reprojection < 0.0 or width <= 0.0:
                raise ValueError("G2 values must be non-negative and width must be > 0")
        except (TypeError, ValueError) as exc:
            return cls._result("G2", INSUFFICIENT_EVIDENCE, {}, {}, _reason_from_exception(exc))
        threshold = max(2.0, 0.05 * width)
        thresholds = {"reprojection_p95_px_max": threshold, "black_line_width_px": width}
        measured = {"reprojection_p95_px": reprojection, "black_line_width_px": width}
        reason = "reprojection p95 above threshold" if reprojection > threshold else ""
        return cls._result("G2", FAIL if reason else PASS, measured, thresholds, reason)

    @classmethod
    def _g3(cls, evidence: object) -> V1GateResult:
        keys = ("detection_rate", "x_p95_mm", "y_p95_mm", "yaw_p95_deg", "black_line_width_mm")
        source, early = cls._evidence("G3", evidence, keys, {})
        if early:
            return early
        assert source is not None
        try:
            detection = _bounded(source["detection_rate"], "detection_rate", 0.0, 1.0)
            x_error = _finite(source["x_p95_mm"], "x_p95_mm")
            y_error = _finite(source["y_p95_mm"], "y_p95_mm")
            yaw = _finite(source["yaw_p95_deg"], "yaw_p95_deg")
            width = _finite(source["black_line_width_mm"], "black_line_width_mm")
            if min(x_error, y_error, yaw) < 0.0 or width <= 0.0:
                raise ValueError("G3 errors must be >= 0 and width must be > 0")
        except (TypeError, ValueError) as exc:
            return cls._result("G3", INSUFFICIENT_EVIDENCE, {}, {}, _reason_from_exception(exc))
        position_limit = 0.05 * width
        thresholds = {"detection_rate_min": 0.95, "position_p95_mm_max": position_limit, "yaw_p95_deg_max": 2.0}
        measured = {"detection_rate": detection, "x_p95_mm": x_error, "y_p95_mm": y_error, "yaw_p95_deg": yaw, "black_line_width_mm": width}
        failures = []
        if detection < 0.95:
            failures.append("detection_rate below 0.95")
        if x_error > position_limit or y_error > position_limit:
            failures.append("x/y p95 above 5% of black-line width")
        if yaw > 2.0:
            failures.append("yaw p95 above 2 degrees")
        return cls._result("G3", FAIL if failures else PASS, measured, thresholds, "; ".join(failures))

    @classmethod
    def _g4(cls, evidence: object) -> V1GateResult:
        keys = ("coverage", "p95_time_diff_ms", "period_bound_ms")
        source, early = cls._evidence("G4", evidence, keys, {})
        if early:
            return early
        assert source is not None
        try:
            coverage = _bounded(source["coverage"], "coverage", 0.0, 1.0)
            p95 = _finite(source["p95_time_diff_ms"], "p95_time_diff_ms")
            period = _finite(source["period_bound_ms"], "period_bound_ms")
            if p95 < 0.0 or period <= 0.0:
                raise ValueError("G4 time values must be non-negative and period must be > 0")
        except (TypeError, ValueError) as exc:
            return cls._result("G4", INSUFFICIENT_EVIDENCE, {}, {}, _reason_from_exception(exc))
        thresholds = {"coverage_min": 0.95, "p95_time_diff_ms_max": period}
        measured = {"coverage": coverage, "p95_time_diff_ms": p95, "period_bound_ms": period}
        failures = []
        if coverage < 0.95:
            failures.append("coverage below 0.95")
        if p95 > period:
            failures.append("p95 time difference above period bound")
        return cls._result("G4", FAIL if failures else PASS, measured, thresholds, "; ".join(failures))

    @classmethod
    def _holdout_section(
        cls, gate_id: str, evidence: object, keys: Sequence[str], thresholds: Mapping[str, Any]
    ) -> tuple[Mapping[str, object] | None, V1GateResult | None]:
        return cls._evidence(gate_id, evidence, keys, thresholds)

    @classmethod
    def _g5(cls, evidence: object) -> V1GateResult:
        thresholds = {"macro_f1_min": 0.90, "semantic_inversion": False, "sample_count_min": 1}
        source, early = cls._holdout_section("G5", evidence, ("macro_f1", "semantic_inversion", "sample_count"), thresholds)
        if early:
            return early
        assert source is not None
        try:
            f1 = _bounded(source["macro_f1"], "macro_f1", 0.0, 1.0)
            inversion = source["semantic_inversion"]
            samples = _count(source["sample_count"], "sample_count")
            if not isinstance(inversion, bool):
                raise ValueError("semantic_inversion must be a bool")
        except (TypeError, ValueError) as exc:
            return cls._result("G5", INSUFFICIENT_EVIDENCE, {}, thresholds, _reason_from_exception(exc))
        measured = {"macro_f1": f1, "semantic_inversion": inversion, "sample_count": samples}
        failures = []
        if f1 < 0.90:
            failures.append("macro-F1 below 0.90")
        if inversion:
            failures.append("sensor semantic inversion detected")
        return cls._result("G5", FAIL if failures else PASS, measured, thresholds, "; ".join(failures))

    @classmethod
    def _g6(cls, evidence: object) -> V1GateResult:
        keys = ("lateral_error_p95_mm", "black_line_width_mm", "terminal_class_accuracy", "sample_count")
        source, early = cls._holdout_section("G6", evidence, keys, {})
        if early:
            return early
        assert source is not None
        try:
            lateral = _finite(source["lateral_error_p95_mm"], "lateral_error_p95_mm")
            width = _finite(source["black_line_width_mm"], "black_line_width_mm")
            accuracy = _bounded(source["terminal_class_accuracy"], "terminal_class_accuracy", 0.0, 1.0)
            samples = _count(source["sample_count"], "sample_count")
            if lateral < 0.0 or width <= 0.0:
                raise ValueError("G6 lateral error must be >= 0 and width must be > 0")
        except (TypeError, ValueError) as exc:
            return cls._result("G6", INSUFFICIENT_EVIDENCE, {}, {}, _reason_from_exception(exc))
        threshold = 0.5 * width
        thresholds = {"lateral_error_p95_mm_max": threshold, "terminal_class_accuracy_min": 1.0, "sample_count_min": 1}
        measured = {"lateral_error_p95_mm": lateral, "black_line_width_mm": width, "terminal_class_accuracy": accuracy, "sample_count": samples}
        failures = []
        if lateral > threshold:
            failures.append("lateral error p95 above half line width")
        if accuracy < 1.0:
            failures.append("terminal class disagreement")
        return cls._result("G6", FAIL if failures else PASS, measured, thresholds, "; ".join(failures))

    @classmethod
    def _g7(cls, evidence: object) -> V1GateResult:
        keys = ("rms_relative_error", "max_relative_error", "completion_time_relative_error", "sample_count")
        source, early = cls._holdout_section("G7", evidence, keys, {})
        if early:
            return early
        assert source is not None
        try:
            rms = _finite(source["rms_relative_error"], "rms_relative_error")
            maximum = _finite(source["max_relative_error"], "max_relative_error")
            completion = _finite(source["completion_time_relative_error"], "completion_time_relative_error")
            samples = _count(source["sample_count"], "sample_count")
            if min(rms, maximum, completion) < 0.0:
                raise ValueError("G7 relative errors must be >= 0")
        except (TypeError, ValueError) as exc:
            return cls._result("G7", INSUFFICIENT_EVIDENCE, {}, {}, _reason_from_exception(exc))
        thresholds = {"rms_relative_error_max": 0.15, "max_relative_error_max": 0.15, "completion_time_relative_error_max": 0.10, "sample_count_min": 1}
        measured = {"rms_relative_error": rms, "max_relative_error": maximum, "completion_time_relative_error": completion, "sample_count": samples}
        failures = []
        if rms > 0.15:
            failures.append("RMS relative error above 0.15")
        if maximum > 0.15:
            failures.append("maximum relative error above 0.15")
        if completion > 0.10:
            failures.append("completion-time error above 0.10")
        return cls._result("G7", FAIL if failures else PASS, measured, thresholds, "; ".join(failures))

    @classmethod
    def _g8(cls, evidence: object) -> V1GateResult:
        keys = ("group_count", "spearman", "danger_recall", "danger_count", "sample_count")
        source, early = cls._holdout_section("G8", evidence, keys, {})
        if early:
            return early
        assert source is not None
        try:
            groups = _count(source["group_count"], "group_count")
            spearman = _bounded(source["spearman"], "spearman", -1.0, 1.0)
            danger_recall = _bounded(source["danger_recall"], "danger_recall", 0.0, 1.0)
            danger_count = _count(source["danger_count"], "danger_count", positive=False)
            samples = _count(source["sample_count"], "sample_count")
        except (TypeError, ValueError) as exc:
            return cls._result("G8", INSUFFICIENT_EVIDENCE, {}, {}, _reason_from_exception(exc))
        thresholds = {"group_count_min": 5, "spearman_min": 0.70, "danger_recall_min": 1.0, "sample_count_min": 1}
        measured = {"group_count": groups, "spearman": spearman, "danger_recall": danger_recall, "danger_count": danger_count, "sample_count": samples}
        if groups > samples or danger_count > samples or danger_count > groups:
            return cls._result(
                "G8",
                INSUFFICIENT_EVIDENCE,
                measured,
                thresholds,
                "impossible group/danger/sample count relationship",
            )
        if danger_count > 0 and danger_recall < 1.0:
            return cls._result("G8", FAIL, measured, thresholds, "danger recall below 100% for observed danger")
        if groups < 5:
            return cls._result("G8", INSUFFICIENT_EVIDENCE, measured, thresholds, "fewer than five unseen PID groups")
        failures = []
        if spearman < 0.70:
            failures.append("Spearman rank below 0.70")
        if danger_recall < 1.0:
            failures.append("danger recall below 100%")
        return cls._result("G8", FAIL if failures else PASS, measured, thresholds, "; ".join(failures))

    @staticmethod
    def _normalize_ids(values: Iterable[str], label: str) -> tuple[Tuple[str, ...], str]:
        if values is None or isinstance(values, (str, bytes)):
            return (), "{} run IDs are missing or not an iterable of strings".format(label)
        try:
            items = tuple(values)
        except Exception as exc:
            return (), "{} run IDs could not be read: {}".format(label, _reason_from_exception(exc))
        normalized = []
        for value in items:
            if not isinstance(value, str) or not value.strip():
                return (), "{} run IDs contain an empty or non-string value".format(label)
            normalized.append(value.strip())
        if len(set(normalized)) != len(normalized):
            return tuple(normalized), "{} run IDs contain duplicates".format(label)
        return tuple(normalized), ""

    @staticmethod
    def _isolation(
        calibration: Tuple[str, ...],
        holdout: Tuple[str, ...],
        *,
        calibration_error: str,
        holdout_error: str,
        model_version: str | None,
        model_version_error: str,
    ) -> Dict[str, Any]:
        if calibration_error or holdout_error:
            return {"status": INSUFFICIENT_EVIDENCE, "reason": "; ".join(x for x in (calibration_error, holdout_error) if x)}
        overlap = sorted(set(calibration).intersection(holdout))
        if overlap:
            return {"status": FAIL, "reason": "calibration/holdout overlap: {}".format(", ".join(overlap))}
        if not calibration or not holdout:
            return {"status": INSUFFICIENT_EVIDENCE, "reason": "calibration and holdout run IDs are required"}
        if model_version_error:
            return {"status": INSUFFICIENT_EVIDENCE, "reason": model_version_error}
        return {"status": PASS, "reason": "calibration and holdout run IDs are disjoint"}

    @staticmethod
    def _normalize_model_version(value: object) -> tuple[str | None, str]:
        if value is None:
            return None, "model_version is required for readiness"
        if not isinstance(value, str):
            return None, "model_version must be a string"
        normalized = value.strip()
        if not normalized:
            return None, "model_version is required for readiness"
        return normalized, ""
