"""Screen bounded OpenCV AprilTag parameter variants on retained images.

This module is intentionally offline-only. It reuses the existing diagnostic
matrix's image loading, preprocessing, detector branch, and summary helpers;
it does not open a camera, connect to TCP, or change the production tracker.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import cv2

try:
    from apriltag_diagnostic_matrix import (
        BRANCH_NAMES,
        _opencv_input,
        _run_opencv,
        _sha256,
        build_branch_result,
        load_image,
        summarize_branch_results,
    )
except ImportError:  # pragma: no cover - package import fallback
    from .apriltag_diagnostic_matrix import (
        BRANCH_NAMES,
        _opencv_input,
        _run_opencv,
        _sha256,
        build_branch_result,
        load_image,
        summarize_branch_results,
    )


PARAMETER_VARIANTS = (
    "default",
    "subpix",
    "contour",
    "adaptive_wide",
    "perimeter_relaxed",
)
DEFAULT_BRANCHES = (
    "opencv_gray_1x",
    "opencv_gray_2x",
    "opencv_blue_2x",
    "opencv_blue_clahe_2x",
)
ROI_PARAMETER_VARIANTS = ("default", "adaptive_wide")
ROI_DEFAULT_BRANCHES = ("opencv_gray_1x", "opencv_blue_2x")


def build_detector_parameters(
    variant: str,
) -> cv2.aruco.DetectorParameters:
    """Return a fresh bounded OpenCV parameter object for one hypothesis."""

    params = cv2.aruco.DetectorParameters()
    if variant == "default":
        return params
    if variant == "subpix":
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        return params
    if variant == "contour":
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_CONTOUR
        return params
    if variant == "adaptive_wide":
        params.adaptiveThreshWinSizeMax = 53
        return params
    if variant == "perimeter_relaxed":
        params.minMarkerPerimeterRate = 0.015
        return params
    raise ValueError("unsupported parameter variant: {0}".format(variant))


def _validate_selection(
    image_paths: Sequence[str | Path],
    branches: Sequence[str],
    variants: Sequence[str],
) -> tuple[tuple[Path, ...], tuple[str, ...], tuple[str, ...]]:
    if not image_paths:
        raise ValueError("at least one image is required")
    if not branches:
        raise ValueError("at least one branch is required")
    if not variants:
        raise ValueError("at least one parameter variant is required")
    supported_branches = set(BRANCH_NAMES)
    unknown_branches = [
        branch for branch in branches if branch not in supported_branches
    ]
    if unknown_branches:
        raise ValueError(
            "unsupported branch: {0}".format(", ".join(unknown_branches))
        )
    unknown_variants = [
        variant for variant in variants if variant not in PARAMETER_VARIANTS
    ]
    if unknown_variants:
        raise ValueError(
            "unsupported parameter variant: {0}".format(
                ", ".join(unknown_variants)
            )
        )
    return (
        tuple(Path(path) for path in image_paths),
        tuple(str(branch) for branch in branches),
        tuple(str(variant) for variant in variants),
    )


def _resolve_roi_bounds(
    image_path: Path,
    roi_bounds: Mapping[str | Path, Sequence[int]],
    image_shape: Sequence[int],
) -> tuple[int, int, int, int]:
    """Resolve and validate a retained ROI without silently clipping it."""

    candidates = (str(image_path), str(image_path.resolve()))
    bounds = None
    for key in candidates:
        if key in roi_bounds:
            bounds = roi_bounds[key]
            break
    if bounds is None:
        for key, value in roi_bounds.items():
            if str(Path(key)) in candidates:
                bounds = value
                break
    if bounds is None:
        raise ValueError("missing ROI bounds for image: {0}".format(image_path))
    if len(bounds) != 4:
        raise ValueError("ROI bounds must contain four values: {0}".format(image_path))
    try:
        normalized = tuple(int(value) for value in bounds)
    except (TypeError, ValueError) as exc:
        raise ValueError("ROI bounds must be integer values: {0}".format(image_path)) from exc
    x0, y0, x1, y1 = normalized
    height, width = int(image_shape[0]), int(image_shape[1])
    if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
        raise ValueError(
            "ROI bounds outside image for {0}: {1}".format(image_path, normalized)
        )
    if x1 <= x0 or y1 <= y0:
        raise ValueError(
            "ROI bounds must have positive area for {0}: {1}".format(
                image_path, normalized
            )
        )
    return normalized


def _record(
    *,
    variant: str,
    branch: str,
    image_path: Path,
    frame: Any,
    elapsed_ns: int,
    ids: Sequence[int],
    rejected_count: int,
    target_id: int,
    target_side_px: Optional[float],
    error: Optional[str],
) -> dict[str, Any]:
    result = build_branch_result(
        branch=branch,
        image_path=str(image_path),
        image_shape=frame.shape,
        elapsed_ns=elapsed_ns,
        ids=ids,
        rejected_count=rejected_count,
        target_id=target_id,
        target_side_px=target_side_px,
        error=error,
    )
    result["parameter_variant"] = variant
    return result


def run_parameter_matrix(
    image_paths: Sequence[str | Path],
    *,
    target_id: int = 0,
    branches: Sequence[str] = DEFAULT_BRANCHES,
    variants: Sequence[str] = PARAMETER_VARIANTS,
) -> dict[str, Any]:
    """Run every selected parameter/preprocessing pair on the same images."""

    selected_images, selected_branches, selected_variants = _validate_selection(
        image_paths, branches, variants
    )
    dictionary = cv2.aruco.getPredefinedDictionary(
        cv2.aruco.DICT_APRILTAG_36h11
    )
    detectors = {
        variant: cv2.aruco.ArucoDetector(
            dictionary, build_detector_parameters(variant)
        )
        for variant in selected_variants
    }

    records: dict[str, dict[str, list[dict[str, Any]]]] = {
        variant: {branch: [] for branch in selected_branches}
        for variant in selected_variants
    }
    image_metadata: list[dict[str, Any]] = []

    for image_path in selected_images:
        frame = load_image(image_path)
        image_metadata.append({
            "image": str(image_path),
            "sha256": _sha256(image_path),
            "shape": [int(value) for value in frame.shape],
            "dtype": str(frame.dtype),
            "contiguous": bool(frame.flags.c_contiguous),
        })
        for variant in selected_variants:
            detector = detectors[variant]
            for branch in selected_branches:
                started_ns = time.perf_counter_ns()
                try:
                    ids, rejected, side_px = _run_opencv(
                        frame, branch, target_id, detector
                    )
                    error = None
                except Exception as exc:  # diagnostics must retain failures
                    ids, rejected, side_px = [], 0, None
                    error = repr(exc)
                records[variant][branch].append(_record(
                    variant=variant,
                    branch=branch,
                    image_path=image_path,
                    frame=frame,
                    elapsed_ns=time.perf_counter_ns() - started_ns,
                    ids=ids,
                    rejected_count=rejected,
                    target_id=target_id,
                    target_side_px=side_px,
                    error=error,
                ))

    flat_records = [
        record
        for variant in selected_variants
        for branch in selected_branches
        for record in records[variant][branch]
    ]
    summaries = {
        variant: {
            branch: summarize_branch_results(records[variant][branch])
            for branch in selected_branches
        }
        for variant in selected_variants
    }
    return {
        "schema_version": 1,
        "type": "V1B3AprilTagParameterMatrix",
        "source": "RETAINED_PARAMETER_SCREENING",
        "evidence_status": "INSUFFICIENT_EVIDENCE",
        "screening_only": True,
        "target_id": int(target_id),
        "opencv_version": str(cv2.__version__),
        "parameter_variants": list(selected_variants),
        "branches": list(selected_branches),
        "images": image_metadata,
        "summaries": summaries,
        "records": flat_records,
    }


def run_roi_parameter_matrix(
    image_paths: Sequence[str | Path],
    *,
    roi_bounds: Mapping[str | Path, Sequence[int]],
    target_id: int = 0,
    branches: Sequence[str] = ROI_DEFAULT_BRANCHES,
    variants: Sequence[str] = ROI_PARAMETER_VARIANTS,
) -> dict[str, Any]:
    """Screen detector variants inside explicitly retained per-image ROIs.

    The ROI is supplied by prior production diagnostics. It is never inferred
    from the same candidate result, so a recovered thumbnail cannot hide a
    full-frame localization failure. This function is offline-only.
    """

    selected_images, selected_branches, selected_variants = _validate_selection(
        image_paths, branches, variants
    )
    dictionary = cv2.aruco.getPredefinedDictionary(
        cv2.aruco.DICT_APRILTAG_36h11
    )
    detectors = {
        variant: cv2.aruco.ArucoDetector(
            dictionary, build_detector_parameters(variant)
        )
        for variant in selected_variants
    }

    records: dict[str, dict[str, list[dict[str, Any]]]] = {
        variant: {branch: [] for branch in selected_branches}
        for variant in selected_variants
    }
    image_metadata: list[dict[str, Any]] = []

    for image_path in selected_images:
        frame = load_image(image_path)
        bounds = _resolve_roi_bounds(image_path, roi_bounds, frame.shape)
        x0, y0, x1, y1 = bounds
        roi_frame = frame[y0:y1, x0:x1].copy()
        height, width = int(frame.shape[0]), int(frame.shape[1])
        roi_height, roi_width = int(roi_frame.shape[0]), int(roi_frame.shape[1])
        image_metadata.append({
            "image": str(image_path),
            "sha256": _sha256(image_path),
            "shape": [int(value) for value in frame.shape],
            "dtype": str(frame.dtype),
            "contiguous": bool(frame.flags.c_contiguous),
            "roi_bounds": list(bounds),
            "roi_shape": [int(value) for value in roi_frame.shape],
        })
        for variant in selected_variants:
            detector = detectors[variant]
            for branch in selected_branches:
                started_ns = time.perf_counter_ns()
                try:
                    ids, rejected, side_px = _run_opencv(
                        roi_frame, branch, target_id, detector
                    )
                    error = None
                except Exception as exc:  # diagnostics must retain failures
                    ids, rejected, side_px = [], 0, None
                    error = repr(exc)
                record = _record(
                    variant=variant,
                    branch=branch,
                    image_path=image_path,
                    frame=frame,
                    elapsed_ns=time.perf_counter_ns() - started_ns,
                    ids=ids,
                    rejected_count=rejected,
                    target_id=target_id,
                    target_side_px=side_px,
                    error=error,
                )
                record.update({
                    "roi_bounds": list(bounds),
                    "roi_shape": [int(value) for value in roi_frame.shape],
                    "roi_area_px": roi_width * roi_height,
                    "roi_area_fraction": (
                        (roi_width * roi_height) / float(width * height)
                    ),
                })
                records[variant][branch].append(record)

    flat_records = [
        record
        for variant in selected_variants
        for branch in selected_branches
        for record in records[variant][branch]
    ]
    summaries = {
        variant: {
            branch: summarize_branch_results(records[variant][branch])
            for branch in selected_branches
        }
        for variant in selected_variants
    }
    return {
        "schema_version": 1,
        "type": "V1B3AprilTagROIParameterMatrix",
        "source": "RETAINED_ROI_PARAMETER_SCREENING",
        "evidence_status": "INSUFFICIENT_EVIDENCE",
        "screening_only": True,
        "roi_policy": "EXPLICIT_RETAINED_BOUNDS",
        "target_id": int(target_id),
        "opencv_version": str(cv2.__version__),
        "parameter_variants": list(selected_variants),
        "branches": list(selected_branches),
        "images": image_metadata,
        "summaries": summaries,
        "records": flat_records,
    }


def _write_json(path: Path, report: dict[str, Any]) -> None:
    if path.exists():
        raise ValueError("refusing to overwrite existing output: {0}".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _parse_roi_spec(spec: str) -> tuple[str, tuple[int, int, int, int]]:
    """Parse ``image-path=x0,y0,x1,y1`` while preserving Windows drive colons."""

    image_path, separator, raw_bounds = spec.rpartition("=")
    if not separator or not image_path:
        raise ValueError("ROI must use image-path=x0,y0,x1,y1")
    values = raw_bounds.split(",")
    if len(values) != 4:
        raise ValueError("ROI must use image-path=x0,y0,x1,y1")
    try:
        bounds = tuple(int(value) for value in values)
    except ValueError as exc:
        raise ValueError("ROI bounds must be integer values") from exc
    return image_path, bounds  # type: ignore[return-value]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Screen bounded AprilTag parameter variants offline."
    )
    parser.add_argument("--image", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-id", type=int, default=0)
    parser.add_argument("--branch", action="append", dest="branches")
    parser.add_argument("--variant", action="append", dest="variants")
    parser.add_argument(
        "--roi",
        action="append",
        dest="roi_specs",
        help="retained ROI as image-path=x0,y0,x1,y1; switches to ROI screening",
    )
    args = parser.parse_args(argv)

    roi_bounds = None
    if args.roi_specs:
        roi_bounds = dict(_parse_roi_spec(spec) for spec in args.roi_specs)
        branches = tuple(args.branches) if args.branches else ROI_DEFAULT_BRANCHES
        variants = tuple(args.variants) if args.variants else ROI_PARAMETER_VARIANTS
    else:
        branches = tuple(args.branches) if args.branches else DEFAULT_BRANCHES
        variants = tuple(args.variants) if args.variants else PARAMETER_VARIANTS
    try:
        if roi_bounds is None:
            report = run_parameter_matrix(
                args.image,
                target_id=args.target_id,
                branches=branches,
                variants=variants,
            )
        else:
            report = run_roi_parameter_matrix(
                args.image,
                roi_bounds=roi_bounds,
                target_id=args.target_id,
                branches=branches,
                variants=variants,
            )
        _write_json(Path(args.output), report)
    except (ValueError, OSError) as exc:
        print("error: {0}".format(exc))
        return 1

    print("parameter matrix report: {0}".format(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
