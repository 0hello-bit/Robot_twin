"""Capture camera-only static AprilTag frames without touching robot control."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional, Sequence

import cv2


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import camera_common as cc  # noqa: E402


DEFAULT_FRAME_COUNT = 100
DEFAULT_WARMUP_FRAMES = 10
JPEG_QUALITY = 95


def frame_filename(index: int) -> str:
    if isinstance(index, bool) or int(index) < 0:
        raise ValueError("frame index must be a non-negative integer")
    return "frame_{:06d}.jpg".format(int(index))


def build_capture_report(
    *,
    output_dir: str,
    requested_width: int,
    requested_height: int,
    requested_fps: float,
    actual_width: int,
    actual_height: int,
    actual_fps: float,
    actual_fourcc: str,
    frame_paths: Sequence[str],
    timestamps_ns: Sequence[int],
    read_failures: int,
) -> dict[str, Any]:
    """Create a fail-closed report for a camera-only capture."""
    timestamps = [int(value) for value in timestamps_ns]
    timestamps_increasing = all(
        left < right for left, right in zip(timestamps, timestamps[1:])
    )
    mode_matches = (
        int(actual_width) == int(requested_width)
        and int(actual_height) == int(requested_height)
        and abs(float(actual_fps) - float(requested_fps)) <= 0.5
        and str(actual_fourcc) == cc.DEFAULT_FOURCC
    )
    capture_verdict = (
        "PASS"
        if mode_matches and timestamps_increasing and int(read_failures) == 0
        else "FAIL"
    )
    return {
        "schema_version": 1,
        "type": "V1B3StaticAprilTagCapture",
        "source": "CAMERA_ONLY",
        "output_dir": str(output_dir),
        "requested": {
            "width": int(requested_width),
            "height": int(requested_height),
            "fps": float(requested_fps),
            "fourcc": cc.DEFAULT_FOURCC,
        },
        "actual": {
            "width": int(actual_width),
            "height": int(actual_height),
            "fps": float(actual_fps),
            "fourcc": str(actual_fourcc),
        },
        "camera_mode": "{0}x{1}/{2}/{3:.1f}".format(
            int(actual_width), int(actual_height), str(actual_fourcc), float(actual_fps)
        ),
        "mode_matches_request": mode_matches,
        "frame_count": len(frame_paths),
        "frame_paths": [str(path) for path in frame_paths],
        "read_failures": int(read_failures),
        "timestamps_ns": timestamps,
        "timestamps_strictly_increasing": timestamps_increasing,
        "capture_verdict": capture_verdict,
        "hardware_control_accessed": False,
        "tcp_accessed": False,
    }


def _fourcc(cap: Any) -> str:
    value = int(cap.get(cv2.CAP_PROP_FOURCC))
    return "".join(chr((value >> (8 * i)) & 0xFF) for i in range(4))


def capture(
    output_dir: str | Path,
    *,
    camera_index: Optional[int] = None,
    frame_count: int = DEFAULT_FRAME_COUNT,
    warmup_frames: int = DEFAULT_WARMUP_FRAMES,
) -> dict[str, Any]:
    """Capture a fixed number of frames from the configured camera only."""
    if isinstance(frame_count, bool) or int(frame_count) <= 0:
        raise ValueError("frame_count must be positive")
    if isinstance(warmup_frames, bool) or int(warmup_frames) < 0:
        raise ValueError("warmup_frames must be non-negative")

    output = Path(output_dir)
    if output.exists():
        raise FileExistsError("refusing to overwrite existing output: {0}".format(output))
    output.mkdir(parents=True, exist_ok=False)
    frames_dir = output / "frames"
    frames_dir.mkdir()

    source = cc.get_camera_index(camera_index)
    cap = None
    frame_paths: list[str] = []
    timestamps_ns: list[int] = []
    read_failures = 0
    try:
        cap, actual_width, actual_height = cc.open_camera(
            source,
            cc.DEFAULT_WIDTH,
            cc.DEFAULT_HEIGHT,
            cc.DEFAULT_FPS,
            cc.DEFAULT_FOURCC,
        )
        actual_fps = float(cap.get(cv2.CAP_PROP_FPS))
        actual_fourcc = _fourcc(cap)
        for _ in range(int(warmup_frames)):
            cap.read()
        while len(frame_paths) < int(frame_count):
            ok, frame = cap.read()
            timestamp_ns = time.perf_counter_ns()
            if not ok or frame is None or frame.size == 0:
                read_failures += 1
                continue
            filename = frame_filename(len(frame_paths))
            encoded, buffer = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
            )
            if not encoded:
                raise RuntimeError(
                    "cv2.imencode returned false for {0} shape={1} dtype={2}".format(
                        filename, tuple(frame.shape), str(frame.dtype)
                    )
                )
            path = frames_dir / filename
            with path.open("xb") as handle:
                handle.write(buffer.tobytes())
            frame_paths.append(str(path.relative_to(output)))
            timestamps_ns.append(int(timestamp_ns))
            if len(frame_paths) % 10 == 0 or len(frame_paths) == int(frame_count):
                print("captured {0}/{1}".format(len(frame_paths), int(frame_count)), flush=True)
    finally:
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()

    report = build_capture_report(
        output_dir=str(output),
        requested_width=cc.DEFAULT_WIDTH,
        requested_height=cc.DEFAULT_HEIGHT,
        requested_fps=cc.DEFAULT_FPS,
        actual_width=actual_width,
        actual_height=actual_height,
        actual_fps=actual_fps,
        actual_fourcc=actual_fourcc,
        frame_paths=frame_paths,
        timestamps_ns=timestamps_ns,
        read_failures=read_failures,
    )
    with (output / "capture_report.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture static AprilTag frames from the camera without TCP or motor control."
    )
    parser.add_argument("output_dir")
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAME_COUNT)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP_FRAMES)
    args = parser.parse_args(argv)
    report = capture(
        args.output_dir,
        camera_index=args.camera,
        frame_count=args.frames,
        warmup_frames=args.warmup,
    )
    print("capture report: {0}".format(Path(args.output_dir) / "capture_report.json"))
    print("mode: {0}".format(report["camera_mode"]))
    print("verdict: {0}".format(report["capture_verdict"]))
    return 0 if report["capture_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
