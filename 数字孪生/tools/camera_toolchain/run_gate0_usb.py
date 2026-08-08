"""4B-1 Gate 0 重验 — EMEET SmartCam C960 (USB index-2), 1280x720, 600s with warm-up.

用法: python run_gate0_usb.py
输出: gate0_report.json, frame_start/mid/end.png, montage.png, gate0_log.txt
判据: fps>=20, drop<=5%, timestamps monotonic, resolution 1280x720 match,
      content valid (no black/near-black/duplicate in official interval).
"""
import json
import os
import sys
import time
import traceback

# Ensure v1_twin is importable
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "..", "simulation", "digital_twin"
))

import cv2
import numpy as np

from v1_twin.v1_twin_camera import OpenCVCameraSource, verify_gate0

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
# DirectShow index 不稳定（热插拔会漂移）。用法: python run_gate0_usb.py [index]
# 2026-08-03 实测 C960 = index 1（曾为 index 2）。

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import camera_common as cc

DURATION = 600.0    # 10 minutes
WIDTH = cc.DEFAULT_WIDTH
HEIGHT = cc.DEFAULT_HEIGHT
FPS = cc.DEFAULT_FPS
FOURCC = "MJPG"
BACKEND = cv2.CAP_DSHOW
WARMUP = True


def make_montage(frame_paths, out_path, label_height=40):
    """Stack frames horizontally with labels (imencode for unicode path)."""
    imgs = []
    labels = ["START", "MID", "END"]
    for p, label in zip(frame_paths, labels):
        if p and os.path.exists(p):
            img = cv2.imread(p)
            if img is None:
                with open(p, "rb") as f:
                    data = f.read()
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            h, w = img.shape[:2]
            target_h = 360
            target_w = int(w * target_h / h)
            img = cv2.resize(img, (target_w, target_h))
            bar = np.ones((label_height, target_w, 3), dtype=np.uint8) * 50
            cv2.putText(bar, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            img = np.vstack([bar, img])
            imgs.append(img)
    if not imgs:
        print("WARNING: no frames to assemble into montage", file=sys.stderr)
        return False
    montage = np.hstack(imgs)
    ok, encoded = cv2.imencode(".png", montage)
    if ok:
        with open(out_path, "wb") as f:
            f.write(encoded.tobytes())
        return True
    return False


def main():
    log_lines = []
    t0 = time.perf_counter()
    source_arg = int(_sys.argv[1]) if len(_sys.argv) > 1 else None
    source = cc.get_camera_index(source_arg)
    source_name = f"EMEET SmartCam C960 (USB DirectShow index-{source})"

    log_lines.append("=== 4B-1 Gate 0 Reacceptance (USB) ===")
    log_lines.append(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log_lines.append(f"Source: {source_name}")
    log_lines.append(
        f"Requested: DirectShow {FOURCC} {WIDTH}x{HEIGHT} @ {FPS:.0f} fps"
    )
    log_lines.append(f"Duration: {DURATION}s")
    log_lines.append(f"Warm-up: {WARMUP}")
    log_lines.append(f"Output dir: {OUT_DIR}")
    log_lines.append("")

    # Pre-flight: check USB camera is available
    try:
        cap_test, actual_w, actual_h = cc.open_camera(
            source,
            width=WIDTH,
            height=HEIGHT,
            fps=FPS,
            fourcc=FOURCC,
            backend=BACKEND,
        )
    except SystemExit as exc:
        log_lines.append(f"PRE-FLIGHT FAIL: {exc}")
        _write_log(log_lines)
        print("\n".join(log_lines))
        return 1
    default_w = int(cap_test.get(cv2.CAP_PROP_FRAME_WIDTH))
    default_h = int(cap_test.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = float(cap_test.get(cv2.CAP_PROP_FPS))
    actual_fourcc_value = int(cap_test.get(cv2.CAP_PROP_FOURCC))
    actual_fourcc = "".join(
        chr((actual_fourcc_value >> (8 * i)) & 0xFF) for i in range(4)
    )
    backend_name = cap_test.getBackendName()
    log_lines.append(
        "Pre-flight actual: "
        f"backend={backend_name}, fourcc={actual_fourcc}, "
        f"resolution={actual_w}x{actual_h}, fps={actual_fps:.3f}"
    )
    cap_test.release()

    log_lines.append("Starting verify_gate0...")
    log_lines.append("")

    try:
        camera_source = OpenCVCameraSource(
            source=source,
            name=source_name,
            width=WIDTH,
            height=HEIGHT,
            backend=BACKEND,
            fps=FPS,
            fourcc=FOURCC,
        )
        stats = verify_gate0(
            source=camera_source,
            duration_s=DURATION,
            out_dir=OUT_DIR,
            save_frames=True,
            width=WIDTH,
            height=HEIGHT,
            warmup_required=WARMUP,
        )
    except Exception as e:
        log_lines.append(f"EXCEPTION during gate: {e}")
        log_lines.append(traceback.format_exc())
        _write_log(log_lines)
        print("\n".join(log_lines))
        return 1

    elapsed = time.perf_counter() - t0
    log_lines.append(f"Gate completed in {elapsed:.1f}s wall-clock")
    log_lines.append("")

    fps = stats.effective_fps
    drop = stats.drop_rate_pct
    mono = stats.timestamps_monotonic
    res_ok = stats.resolution_match
    content_ok = stats.invalid_content_frames == 0

    fps_gate = fps >= 20.0
    drop_gate = drop <= 5.0
    mono_gate = mono
    all_passed = fps_gate and drop_gate and mono_gate and res_ok and content_ok

    report = {
        "gate": "G1 (4B-1 Fresh Reacceptance)",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source_name,
        "capture_mode": {
            "backend": backend_name,
            "fourcc": actual_fourcc,
            "requested_fps": FPS,
            "driver_fps": round(actual_fps, 3),
        },
        "duration_s": round(stats.duration_s, 3),
        "wall_clock_s": round(elapsed, 1),
        "frame_count": stats.frame_count,
        "effective_fps": round(fps, 2),
        "nominal_period_ms": round(stats.nominal_period_ms, 3),
        "drop_rate_pct": round(drop, 3),
        "timestamps_monotonic": mono,
        "dropped_frames": stats.dropped_frames,
        "expected_frames": stats.expected_frames,
        "duplicate_rate_pct": stats.duplicate_rate_pct,
        "drop_detection": "gap>1.5x mean-interval",
        "resolution": {
            "requested": f"{WIDTH}x{HEIGHT}",
            "actual": f"{stats.actual_width}x{stats.actual_height}",
            "match": res_ok,
            "actual_width": stats.actual_width,
            "actual_height": stats.actual_height,
            "preflight_default": f"{default_w}x{default_h}",
        },
        "warmup": {
            "enabled": WARMUP,
            "frames_discarded": stats.warmup_frames_discarded,
        },
        "content_validity": {
            "invalid_frames_in_official_interval": stats.invalid_content_frames,
            "duplicate_rate_pct": stats.duplicate_rate_pct,
        },
        "verdict": "PASS" if all_passed else "FAIL",
        "verdict_details": {
            "fps_gate": fps_gate,
            "drop_gate": drop_gate,
            "monotonic_gate": mono_gate,
            "resolution_gate": res_ok,
            "content_gate": content_ok,
        },
        "status": "PENDING_INDEPENDENT_VISUAL_REVIEW",
    }

    report_path = os.path.join(OUT_DIR, "gate0_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log_lines.append("=== Report ===")
    log_lines.append(json.dumps(report, ensure_ascii=False, indent=2))
    log_lines.append("")

    frame_names = ["frame_start.png", "frame_mid.png", "frame_end.png"]
    frame_paths = [os.path.join(OUT_DIR, n) for n in frame_names]
    existing = [p for p in frame_paths if os.path.exists(p)]
    log_lines.append(f"Saved frames: {len(existing)}/3")
    for n, p in zip(frame_names, frame_paths):
        status = "EXISTS" if os.path.exists(p) else "MISSING"
        size = os.path.getsize(p) if os.path.exists(p) else 0
        log_lines.append(f"  {n}: {status} ({size} bytes)")

    montage_path = os.path.join(OUT_DIR, "montage.png")
    if len(existing) >= 1:
        ok = make_montage(frame_paths, montage_path)
        log_lines.append(f"Montage: {'OK' if ok else 'FAILED'} -> {montage_path}")
    else:
        log_lines.append("Montage: SKIPPED (no frames)")

    log_lines.append("")
    log_lines.append(f"=== FINAL: {report['verdict']} ===")
    log_lines.append(f"Status: {report['status']}")
    log_lines.append(f"Resolution actual: {stats.actual_width}x{stats.actual_height}")
    log_lines.append("")
    if not all_passed:
        failures = []
        if not fps_gate: failures.append(f"fps={fps:.2f} < 20")
        if not drop_gate: failures.append(f"drop={drop:.3f}% > 5%")
        if not mono_gate: failures.append("non-monotonic timestamps")
        if not res_ok: failures.append(f"resolution {stats.actual_width}x{stats.actual_height} != {WIDTH}x{HEIGHT}")
        if not content_ok: failures.append(f"invalid_content={stats.invalid_content_frames} > 0")
        log_lines.append(f"Failures: {'; '.join(failures)}")
    log_lines.append("READY_FOR_INDEPENDENT_REVIEW" if all_passed else "BLOCKED")

    _write_log(log_lines)
    print("\n".join(log_lines))
    return 0 if all_passed else 1


def _write_log(lines):
    log_path = os.path.join(OUT_DIR, "gate0_log.txt")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
