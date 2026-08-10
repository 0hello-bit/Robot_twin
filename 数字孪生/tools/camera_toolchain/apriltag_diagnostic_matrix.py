"""Run independent AprilTag detection branches on retained image frames.

This tool is intentionally read-only with respect to production tracking. It
does not use the stateful ROI, camera, TCP, calibration, or vehicle control.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import cv2
import numpy as np

try:
    from camera_common import imread_unicode
except ImportError:  # pragma: no cover - package import fallback
    from .camera_common import imread_unicode


BRANCH_NAMES = (
    "opencv_gray_1x",
    "opencv_gray_2x",
    "opencv_gray_3x",
    "opencv_blue_2x",
    "opencv_green_2x",
    "opencv_red_2x",
    "opencv_blue_clahe_2x",
    "opencv_blue_unsharp_2x",
    "opencv_gray_clahe_2x",
    "opencv_adaptive_2x",
    "pupil_gray_1x",
    "pupil_gray_2x",
)


def load_image(path: str | Path) -> np.ndarray:
    """Load a retained image through the workspace's Unicode-safe IO path."""
    try:
        return imread_unicode(str(path))
    except (OSError, ValueError) as exc:
        raise ValueError("unable to decode image: {0}".format(path)) from exc


def _percentile(values: Iterable[int], percentile: float) -> int:
    ordered = sorted(int(value) for value in values)
    if not ordered:
        raise ValueError("at least one timing value is required")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return int(round(ordered[lower] + fraction * (ordered[upper] - ordered[lower])))


def build_branch_result(
    *,
    branch: str,
    image_path: str,
    image_shape: Sequence[int],
    elapsed_ns: int,
    ids: Sequence[int],
    rejected_count: int,
    target_id: int,
    target_side_px: Optional[float] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    """Build one JSON-safe result record for a detector branch."""
    if branch not in BRANCH_NAMES:
        raise ValueError("unsupported branch: {0}".format(branch))
    normalized_ids = [int(value) for value in ids]
    return {
        "branch": branch,
        "image": str(image_path),
        "image_shape": [int(value) for value in image_shape],
        "target_id": int(target_id),
        "ids": normalized_ids,
        "target_detected": int(target_id) in normalized_ids,
        "rejected_count": int(rejected_count),
        "target_side_px": (
            None if target_side_px is None else float(target_side_px)
        ),
        "elapsed_ns": int(elapsed_ns),
        "error": error,
    }


def summarize_branch_results(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Summarize records from exactly one branch."""
    if not results:
        raise ValueError("at least one branch result is required")
    branches = {str(result.get("branch")) for result in results}
    if len(branches) != 1:
        raise ValueError("all results must belong to the same branch")
    branch = next(iter(branches))
    elapsed = [int(result["elapsed_ns"]) for result in results]
    detected = sum(1 for result in results if result["target_detected"])
    return {
        "branch": branch,
        "image_count": len(results),
        "detected_count": detected,
        "detection_ratio": detected / len(results),
        "rejected_candidate_total": sum(
            int(result["rejected_count"]) for result in results
        ),
        "processing_p95_ns": _percentile(elapsed, 0.95),
    }


def _resize(image: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0:
        return image
    return cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )


def _gray_input(frame: np.ndarray, scale: float) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return np.ascontiguousarray(_resize(gray, scale), dtype=np.uint8)


def _opencv_input(frame: np.ndarray, branch: str) -> np.ndarray:
    if branch.startswith("opencv_gray_"):
        scale = float(branch.rsplit("_", 1)[1][:-1])
        return _gray_input(frame, scale)

    if branch == "opencv_blue_2x":
        return np.ascontiguousarray(_resize(frame[:, :, 0], 2.0), dtype=np.uint8)
    if branch == "opencv_green_2x":
        return np.ascontiguousarray(_resize(frame[:, :, 1], 2.0), dtype=np.uint8)
    if branch == "opencv_red_2x":
        return np.ascontiguousarray(_resize(frame[:, :, 2], 2.0), dtype=np.uint8)

    if branch in {
        "opencv_blue_clahe_2x",
        "opencv_blue_unsharp_2x",
        "opencv_gray_clahe_2x",
        "opencv_adaptive_2x",
    }:
        if branch.startswith("opencv_blue"):
            source = frame[:, :, 0]
        else:
            source = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        source = _resize(source, 2.0)
        if branch.endswith("clahe_2x"):
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
            return np.ascontiguousarray(clahe.apply(source), dtype=np.uint8)
        if branch == "opencv_blue_unsharp_2x":
            blur = cv2.GaussianBlur(source, (0, 0), 1.0)
            return np.ascontiguousarray(
                cv2.addWeighted(source, 2.0, blur, -1.0, 0), dtype=np.uint8
            )
        return np.ascontiguousarray(
            cv2.adaptiveThreshold(
                source,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                5,
            ),
            dtype=np.uint8,
        )

    raise ValueError("unsupported OpenCV branch: {0}".format(branch))


def _target_side_from_corners(corners: Any, scale: float) -> float:
    points = np.asarray(corners[0], dtype=float) / scale
    return float(np.linalg.norm(points[0] - points[1]))


def _run_opencv(
    frame: np.ndarray,
    branch: str,
    target_id: int,
    detector: Any,
) -> tuple[list[int], int, Optional[float]]:
    image = _opencv_input(frame, branch)
    corners, ids, rejected = detector.detectMarkers(image)
    found_ids = [] if ids is None else [int(value) for value in ids.ravel()]
    side_px = None
    if ids is not None:
        scale = 1.0
        if branch.endswith("_2x"):
            scale = 2.0
        elif branch.endswith("_3x"):
            scale = 3.0
        for marker_corners, marker_id in zip(corners, found_ids):
            if marker_id == int(target_id):
                side_px = _target_side_from_corners(marker_corners, scale)
                break
    rejected_count = 0 if rejected is None else len(rejected)
    return found_ids, rejected_count, side_px


def _load_pupil_detector() -> Any:
    from pupil_apriltags import Detector

    return Detector(
        families="tag36h11",
        nthreads=1,
        quad_decimate=1.0,
        quad_sigma=0.0,
        refine_edges=1,
    )


def _run_pupil(
    frame: np.ndarray,
    branch: str,
    target_id: int,
    detector: Any,
) -> tuple[list[int], int, Optional[float]]:
    scale = 1.0 if branch.endswith("_1x") else 2.0
    image = _gray_input(frame, scale)
    detections = detector.detect(image, estimate_tag_pose=False)
    found_ids = [int(detection.tag_id) for detection in detections]
    side_px = None
    for detection in detections:
        if int(detection.tag_id) == int(target_id):
            points = np.asarray(detection.corners, dtype=float) / scale
            side_px = float(np.linalg.norm(points[0] - points[1]))
            break
    return found_ids, 0, side_px


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_matrix(
    image_paths: Sequence[str | Path],
    *,
    target_id: int = 0,
    branches: Sequence[str] = BRANCH_NAMES,
) -> dict[str, Any]:
    """Run all requested branches over the exact same retained images."""
    selected = tuple(branches)
    unknown = [branch for branch in selected if branch not in BRANCH_NAMES]
    if unknown:
        raise ValueError("unsupported branches: {0}".format(", ".join(unknown)))
    if not image_paths:
        raise ValueError("at least one image is required")

    opencv_dictionary = cv2.aruco.getPredefinedDictionary(
        cv2.aruco.DICT_APRILTAG_36h11
    )
    opencv_detector = cv2.aruco.ArucoDetector(
        opencv_dictionary, cv2.aruco.DetectorParameters()
    )
    pupil_detector = None
    if any(branch.startswith("pupil_") for branch in selected):
        if importlib.util.find_spec("pupil_apriltags") is not None:
            pupil_detector = _load_pupil_detector()

    records: list[dict[str, Any]] = []
    image_metadata: list[dict[str, Any]] = []
    for image_path in image_paths:
        path = Path(image_path)
        frame = load_image(path)
        image_metadata.append({
            "image": str(path),
            "sha256": _sha256(path),
            "shape": [int(value) for value in frame.shape],
            "dtype": str(frame.dtype),
            "contiguous": bool(frame.flags.c_contiguous),
        })
        for branch in selected:
            started_ns = time.perf_counter_ns()
            try:
                if branch.startswith("pupil_"):
                    if pupil_detector is None:
                        raise RuntimeError("pupil_apriltags is unavailable")
                    ids, rejected, side_px = _run_pupil(
                        frame, branch, target_id, pupil_detector
                    )
                else:
                    ids, rejected, side_px = _run_opencv(
                        frame, branch, target_id, opencv_detector
                    )
                error = None
            except Exception as exc:  # diagnostics must retain branch failures
                ids, rejected, side_px = [], 0, None
                error = repr(exc)
            records.append(build_branch_result(
                branch=branch,
                image_path=str(path),
                image_shape=frame.shape,
                elapsed_ns=time.perf_counter_ns() - started_ns,
                ids=ids,
                rejected_count=rejected,
                target_id=target_id,
                target_side_px=side_px,
                error=error,
            ))

    summaries = {
        branch: summarize_branch_results(
            [record for record in records if record["branch"] == branch]
        )
        for branch in selected
    }
    return {
        "schema_version": 1,
        "type": "V1B3AprilTagOfflineDetectorMatrix",
        "source": "RETAINED_FAILURE_FRAMES",
        "target_id": int(target_id),
        "opencv_version": str(cv2.__version__),
        "pupil_apriltags_available": pupil_detector is not None,
        "branches": list(selected),
        "images": image_metadata,
        "summaries": summaries,
        "records": records,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare independent AprilTag branches on retained images."
    )
    parser.add_argument("--image", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-id", type=int, default=0)
    args = parser.parse_args(argv)

    output = Path(args.output)
    if output.exists():
        raise SystemExit("refusing to overwrite existing output: {0}".format(output))
    report = run_matrix(args.image, target_id=args.target_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print("matrix report: {0}".format(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
