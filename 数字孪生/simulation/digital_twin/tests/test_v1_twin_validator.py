import json
import math

from v1_twin.v1_twin_validator import V1TwinValidator


def valid_g1_to_g4():
    return {
        "G1": {
            "fps": 20.0,
            "drop_rate": 0.05,
            "timestamps_monotonic": True,
            "invalid_frames": 0,
        },
        "G2": {
            "reprojection_p95_px": 2.0,
            "black_line_width_px": 20.0,
        },
        "G3": {
            "detection_rate": 0.95,
            "x_p95_mm": 1.0,
            "y_p95_mm": 1.0,
            "yaw_p95_deg": 2.0,
            "black_line_width_mm": 20.0,
        },
        "G4": {
            "coverage": 0.95,
            "p95_time_diff_ms": 33.3,
            "period_bound_ms": 33.3,
        },
    }


def valid_holdout():
    return {
        "g5": {
            "macro_f1": 0.90,
            "semantic_inversion": False,
            "sample_count": 5,
        },
        "g6": {
            "lateral_error_p95_mm": 10.0,
            "black_line_width_mm": 20.0,
            "terminal_class_accuracy": 1.0,
            "sample_count": 5,
        },
        "g7": {
            "rms_relative_error": 0.15,
            "max_relative_error": 0.15,
            "completion_time_relative_error": 0.10,
            "sample_count": 5,
        },
        "g8": {
            "group_count": 5,
            "spearman": 0.70,
            "danger_recall": 1.0,
            "danger_count": 0,
            "sample_count": 25,
        },
    }


def test_empty_evidence_is_insufficient_not_ready():
    report = V1TwinValidator.evaluate(None, None)

    assert report.verdict == "INSUFFICIENT_EVIDENCE"
    assert set(report.gates) == {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"}
    assert all(g.status == "INSUFFICIENT_EVIDENCE" for g in report.gates.values())


def test_all_thresholds_at_boundary_produce_ready():
    report = V1TwinValidator.evaluate(
        valid_g1_to_g4(),
        valid_holdout(),
        calibration_run_ids=("cal-1",),
        holdout_run_ids=("hold-1", "hold-2", "hold-3", "hold-4", "hold-5"),
        model_version="model-1",
    )

    assert report.verdict == "READY"
    assert all(g.status == "PASS" for g in report.gates.values())
    assert report.data_isolation["status"] == "PASS"


def test_explicit_monotonicity_failure_is_not_insufficient_evidence():
    evidence = valid_g1_to_g4()
    evidence["G1"]["timestamps_monotonic"] = False

    report = V1TwinValidator.evaluate(evidence, valid_holdout())

    assert report.verdict == "NOT_READY"
    assert report.gates["G1"].status == "FAIL"


def test_holdout_overlap_fails_isolation():
    report = V1TwinValidator.evaluate(
        valid_g1_to_g4(),
        valid_holdout(),
        calibration_run_ids=("same",),
        holdout_run_ids=("same",),
    )

    assert report.verdict == "NOT_READY"
    assert report.data_isolation["status"] == "FAIL"


def test_missing_or_malformed_evidence_is_insufficient():
    evidence = valid_g1_to_g4()
    evidence["G1"] = {"fps": math.nan}
    holdout = valid_holdout()
    del holdout["g6"]

    report = V1TwinValidator.evaluate(evidence, holdout)

    assert report.verdict == "INSUFFICIENT_EVIDENCE"
    assert report.gates["G1"].status == "INSUFFICIENT_EVIDENCE"
    assert report.gates["G6"].status == "INSUFFICIENT_EVIDENCE"


def test_negative_rate_malformed_failure_flag_and_string_number_are_insufficient():
    evidence = valid_g1_to_g4()
    evidence["G1"]["fps"] = -1.0
    report = V1TwinValidator.evaluate(evidence, valid_holdout())
    assert report.gates["G1"].status == "INSUFFICIENT_EVIDENCE"

    evidence = valid_g1_to_g4()
    evidence["G1"]["observed_failure"] = 1
    report = V1TwinValidator.evaluate(evidence, valid_holdout())
    assert report.gates["G1"].status == "INSUFFICIENT_EVIDENCE"

    evidence = valid_g1_to_g4()
    evidence["G1"]["fps"] = "20"
    report = V1TwinValidator.evaluate(evidence, valid_holdout())
    assert report.gates["G1"].status == "INSUFFICIENT_EVIDENCE"


def test_g1_threshold_violation_fails():
    evidence = valid_g1_to_g4()
    evidence["G1"]["drop_rate"] = 0.051
    report = V1TwinValidator.evaluate(evidence, valid_holdout())
    assert report.gates["G1"].status == "FAIL"
    assert "drop" in report.gates["G1"].reason


def test_g2_and_g3_threshold_violations_fail():
    evidence = valid_g1_to_g4()
    evidence["G2"]["reprojection_p95_px"] = 2.01
    evidence["G3"]["yaw_p95_deg"] = 2.01
    report = V1TwinValidator.evaluate(evidence, valid_holdout())
    assert report.gates["G2"].status == "FAIL"
    assert report.gates["G3"].status == "FAIL"


def test_g4_threshold_violation_fails():
    evidence = valid_g1_to_g4()
    evidence["G4"]["coverage"] = 0.949
    report = V1TwinValidator.evaluate(evidence, valid_holdout())
    assert report.gates["G4"].status == "FAIL"


def test_g5_inversion_and_g6_terminal_mismatch_fail():
    holdout = valid_holdout()
    holdout["g5"]["semantic_inversion"] = True
    holdout["g6"]["terminal_class_accuracy"] = 0.99
    report = V1TwinValidator.evaluate(valid_g1_to_g4(), holdout)
    assert report.gates["G5"].status == "FAIL"
    assert report.gates["G6"].status == "FAIL"


def test_g7_and_g8_bad_metrics_block_ready():
    holdout = valid_holdout()
    holdout["g7"]["max_relative_error"] = 0.151
    holdout["g8"]["spearman"] = 0.699
    report = V1TwinValidator.evaluate(valid_g1_to_g4(), holdout)
    assert report.verdict == "NOT_READY"
    assert report.gates["G7"].status == "FAIL"
    assert report.gates["G8"].status == "FAIL"


def test_g8_danger_recall_failure_is_explicit_fail():
    holdout = valid_holdout()
    holdout["g8"]["danger_count"] = 1
    holdout["g8"]["danger_recall"] = 0.0
    report = V1TwinValidator.evaluate(valid_g1_to_g4(), holdout)
    assert report.gates["G8"].status == "FAIL"


def test_impossible_g8_counts_are_insufficient_evidence():
    holdout = valid_holdout()
    holdout["g8"]["danger_count"] = 100
    holdout["g8"]["sample_count"] = 1
    report = V1TwinValidator.evaluate(valid_g1_to_g4(), holdout)
    assert report.gates["G8"].status == "INSUFFICIENT_EVIDENCE"


def test_g8_fewer_groups_is_insufficient_evidence():
    holdout = valid_holdout()
    holdout["g8"]["group_count"] = 4
    report = V1TwinValidator.evaluate(valid_g1_to_g4(), holdout)
    assert report.gates["G8"].status == "INSUFFICIENT_EVIDENCE"
    assert report.verdict == "INSUFFICIENT_EVIDENCE"


def test_g8_danger_miss_is_fail_even_when_group_count_is_small():
    holdout = valid_holdout()
    holdout["g8"].update(group_count=4, danger_count=1, danger_recall=0.0, sample_count=4)
    report = V1TwinValidator.evaluate(valid_g1_to_g4(), holdout)
    assert report.gates["G8"].status == "FAIL"
    assert report.verdict == "NOT_READY"


def test_conflicting_failure_aliases_keep_explicit_failure():
    evidence = valid_g1_to_g4()
    evidence["G1"].update(observed_failure=False, failure="danger observed")
    report = V1TwinValidator.evaluate(evidence, valid_holdout())
    assert report.gates["G1"].status == "FAIL"


def test_run_id_generator_error_is_insufficient_not_an_exception():
    def broken_ids():
        raise RuntimeError("id source failed")
        yield "never"

    report = V1TwinValidator.evaluate(None, None, calibration_run_ids=broken_ids())
    assert report.verdict == "INSUFFICIENT_EVIDENCE"
    assert report.data_isolation["status"] == "INSUFFICIENT_EVIDENCE"


def test_non_string_model_version_does_not_break_report_serialization():
    report = V1TwinValidator.evaluate(None, None, model_version=123)
    json.dumps(report.to_dict(), sort_keys=True)
    assert report.model_version is None


def test_report_serialization_is_json_compatible():
    report = V1TwinValidator.evaluate(
        valid_g1_to_g4(),
        valid_holdout(),
        calibration_run_ids=("cal-1",),
        holdout_run_ids=("hold-1", "hold-2", "hold-3", "hold-4", "hold-5"),
        model_version="model-1",
    )
    encoded = json.dumps(report.to_dict(), sort_keys=True)
    assert '"verdict": "READY"' in encoded


def test_id_normalization_catches_whitespace_overlap_and_duplicates():
    report = V1TwinValidator.evaluate(
        valid_g1_to_g4(),
        valid_holdout(),
        calibration_run_ids=(" x ",),
        holdout_run_ids=("x",),
        model_version="model-1",
    )
    assert report.verdict == "NOT_READY"
    assert report.data_isolation["status"] == "FAIL"
    assert report.calibration_run_ids == ("x",)

    report = V1TwinValidator.evaluate(
        valid_g1_to_g4(),
        valid_holdout(),
        calibration_run_ids=("x", " x "),
        holdout_run_ids=("hold",),
        model_version="model-1",
    )
    assert report.data_isolation["status"] == "INSUFFICIENT_EVIDENCE"
