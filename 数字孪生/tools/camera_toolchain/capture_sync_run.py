"""Task 4B-4 同步采集 + 时间对齐验证（真车运行）。

流程:
  1. 连摄像头 (index1, 1280x720) + 小车 WiFi (ESP01S TCP 8888)
  2. 读取相机**实际**帧尺寸并与 CameraCalibration.image_size / homography
     严格核对；不一致立即 FAIL（Task 4B-4 fix，cap.set 不能作为成功证据）。
  3. 打印 READY，等待小车开始跑（出现第一帧遥测，30s 超时）
  4. 出现遥测后采集 *duration_s* 秒：相机位姿 (V1Pose) + 遥测 (V1TelemetryFrame)
     - 相机帧成功读取后**立即**记录 time.monotonic_ns() 并显式传入
       PoseTracker.track(frame, t_pc_ns=...)，不在检测结束后打采集时间。
     - 遥测保留有符号 PWM（不钳零丢方向）与 yaw_rad。
  5. 用 (tick_ms, pc_recv_ns) 拟合 ClockSync（批量投递 → fit_batched）
  6. build_synchronized_dataset → 共同区间 coverage / 全量 p95 + 诊断指标
  7. evaluate_sync_gate → PASS / FAIL / INSUFFICIENT EVIDENCE
  8. 原始数据写入独立 run_id 目录，目标文件已存在时 fail closed

START 之后的资源清理（Task 4B-4 fix, Codex review remediation）:
  - `run_sync_capture_session()` 把 START→等待→采集 的生命周期与统一、幂等的
    清理绑定：无论正常、无遥测超时、采集异常、STOP 发送失败，socket.close 与
    cap.release 都恰好执行一次；START 发送失败时不会假称已发送 STOP。
  - 该函数接受注入的 sock/cap，离线测试可用 fake socket/camera 验证清理契约。

⚠️ 运行会发送 START/STOP 并驱动小车，必须在用户授权 + 赛道净空下执行。
   （本任务只修改代码与离线测试，不运行本脚本。）

用法:
    python capture_sync_run.py --host 192.168.110.236 --duration 12 --out .
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sys
import threading
import time

import numpy as np

_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_WORKSPACE_ROOT / "simulation" / "digital_twin"))
sys.path.insert(0, str(_WORKSPACE_ROOT / "tools" / "camera_toolchain"))
sys.path.insert(0, str(_WORKSPACE_ROOT / "tools" / "shakedown_toolchain"))

import cv2
import camera_common

from v1_twin.v1_twin_calibration import CameraCalibration, HomographyTransform
from v1_twin.v1_twin_capture import (
    resolve_run_output_dir,
    validate_frame_dimensions,
)
from v1_twin.v1_twin_dataset import (
    build_synchronized_dataset,
    evaluate_sync_gate,
)
from v1_twin.v1_twin_pose_tracker import PoseTracker
from v1_twin.v1_twin_pose_fusion import V1PoseFusion
from v1_twin.v1_twin_imu_control import summarize_imu_evidence
from v1_twin.v1_twin_motion_evidence import build_camera_motion_evidence
from v1_twin.v1_twin_schema import V1TelemetryFrame, V1Pose
from v1_twin.v1_twin_sync import ClockSync
from real_world.frame_parser import decode_health, decode_telemetry
from real_world.runtime_protocol import (
    RunCommand,
    make_runtime_identifier,
    parse_status,
)
from transport_soak import (
    HEARTBEAT_PERIOD_S,
    HeartbeatCommand,
    MixedStreamParser,
    RawIoLogger,
    compute_health_summary,
)

CAMERA_WIDTH = camera_common.DEFAULT_WIDTH
CAMERA_HEIGHT = camera_common.DEFAULT_HEIGHT
CAMERA_FPS = camera_common.DEFAULT_FPS
CAMERA_PERIOD_NS = int(round(1_000_000_000 / CAMERA_FPS))
TELEMETRY_PERIOD_NS = 30_000_000  # firmware generation interval
TOLERANCE_NS = max(CAMERA_PERIOD_NS, TELEMETRY_PERIOD_NS)
STOP_CONFIRM_TIMEOUT_S = 1.0
READER_JOIN_TIMEOUT_S = 1.0


# Windows monotonic_ns may be backed by a coarse GetTickCount64 clock.
_capture_pc_clock_lock = threading.Lock()
_last_capture_pc_clock_ns = None


def capture_pc_clock_ns():
    """Return a shared high-resolution clock that is strictly increasing."""
    global _last_capture_pc_clock_ns
    with _capture_pc_clock_lock:
        now_ns = time.perf_counter_ns()
        if (
            _last_capture_pc_clock_ns is not None
            and now_ns <= _last_capture_pc_clock_ns
        ):
            now_ns = _last_capture_pc_clock_ns + 1
        _last_capture_pc_clock_ns = now_ns
        return now_ns

OUTPUT_FILENAMES = (
    "pose.jsonl",
    "telemetry.jsonl",
    "frame_index.jsonl",
    "fusion.jsonl",
    "raw_poses.json",
    "raw_telemetry.json",
    "raw_health.json",
    "raw_io.json",
    "sync_report.json",
    "imu_evidence.json",
    "camera_motion.jsonl",
    "motion_evidence.json",
)
B3_RAW_FILENAMES = ("pose.jsonl", "telemetry.jsonl", "frame_index.jsonl")
B3_DIAGNOSTIC_FILENAMES = ("raw_health.json", "raw_io.json")

FAILURE_FRAME_DIRNAME = "failed_frames"
MAX_FAILURE_FRAME_THUMBNAILS = 12
FAILURE_FRAME_SAMPLE_STRIDE = 30
FAILURE_FRAME_MAX_WIDTH = CAMERA_WIDTH
FAILURE_FRAME_JPEG_QUALITY = 95


def open_capture_camera(index: int):
    """Open the C960 in the mode accepted by the 4B-4 capture gate."""
    cap, actual_w, actual_h = camera_common.open_camera(
        int(index),
        width=CAMERA_WIDTH,
        height=CAMERA_HEIGHT,
        fps=CAMERA_FPS,
        fourcc="MJPG",
        backend=cv2.CAP_DSHOW,
    )
    if (actual_w, actual_h) != (CAMERA_WIDTH, CAMERA_HEIGHT):
        cap.release()
        raise SystemExit(
            "capture requires {}x{}, got {}x{}".format(
                CAMERA_WIDTH, CAMERA_HEIGHT, actual_w, actual_h
            )
        )
    return cap, actual_w, actual_h


def read_camera_mode(cap, index, width, height):
    """Read the actual capture mode for immutable run evidence."""
    fourcc_value = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc = "".join(
        chr((fourcc_value >> (8 * i)) & 0xFF) for i in range(4)
    )
    return {
        "index": int(index),
        "width": int(width),
        "height": int(height),
        "fps": float(cap.get(cv2.CAP_PROP_FPS)),
        "fourcc": fourcc,
    }


def make_run_id() -> str:
    """Generate a wire-compatible capture run ID for directory and status evidence."""
    return make_runtime_identifier("c")


def binarize_sensor(v):
    """固件 s0-s3 二值化：>0 → 1（1=白底，0=黑线，权威定义=固件阈值）。"""
    return 1 if int(v) > 0 else 0


# ── 资源清理（Task 4B-4 fix, Codex review remediation）───────────────
#
# 所有 START 之后的路径都必须进入同一个清理结构；清理是幂等的，重复调用
# 不重复执行。STOP 发送失败仍继续关闭 socket 和相机。START 未发出则不
# 发送 STOP（不得假称已经 STOP）。


def _new_action_state():
    """初始化动作报告字典。"""
    return {
        "start_sent": False,
        "start_error": None,
        "heartbeat_sent": 0,
        "heartbeat_error": None,
        "collect_error": None,
        "stop_attempted": False,
        "stop_sent": False,
        "stop_error": None,
        "stop_confirmed": False,
        "stop_status": None,
        "stop_confirm_error": None,
        "socket_closed": False,
        "close_error": None,
        "camera_released": False,
        "release_error": None,
        "reader_joined": False,
        "reader_join_error": None,
        "reader_error": None,
        "status_events": [],
        "status_parse_errors": [],
        "cleaned_up": False,
    }


def _new_failure_frame_summary(failure_frame_dir, max_saved):
    return {
        "enabled": failure_frame_dir is not None and int(max_saved) > 0,
        "directory": (
            Path(failure_frame_dir).name if failure_frame_dir is not None else None
        ),
        "max_saved": max(0, int(max_saved)),
        "sample_stride": FAILURE_FRAME_SAMPLE_STRIDE,
        "max_width": FAILURE_FRAME_MAX_WIDTH,
        "jpeg_quality": FAILURE_FRAME_JPEG_QUALITY,
        "saved": 0,
        "observed": 0,
        "by_reason": {},
        "saved_by_reason": {},
        "save_errors": [],
    }


def _failure_frame_filename(frame_index, reason):
    safe_reason = "".join(
        char if char.isalnum() or char in "-_" else "_"
        for char in str(reason)
    ) or "unknown"
    return "frame_{:06d}_{}.jpg".format(int(frame_index), safe_reason)


def _save_failure_frame_thumbnail(frame, frame_index, reason, failure_frame_dir):
    """Save one bounded diagnostic image and return its run-relative path."""
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        return None, "frame is not a non-empty numpy array"
    try:
        output_dir = Path(failure_frame_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        image = frame
        if image.ndim < 2:
            return None, "frame has no image dimensions"
        height, width = image.shape[:2]
        if width > FAILURE_FRAME_MAX_WIDTH:
            target_height = max(1, round(height * FAILURE_FRAME_MAX_WIDTH / width))
            image = cv2.resize(
                image,
                (FAILURE_FRAME_MAX_WIDTH, target_height),
                interpolation=cv2.INTER_AREA,
            )
        filename = _failure_frame_filename(frame_index, reason)
        path = output_dir / filename
        if not cv2.imwrite(
            str(path), image,
            [cv2.IMWRITE_JPEG_QUALITY, FAILURE_FRAME_JPEG_QUALITY],
        ):
            return None, "cv2.imwrite returned false"
        return "{}/{}".format(output_dir.name, filename), None
    except BaseException as exc:  # noqa: BLE001 - diagnostics must not stop capture
        return None, repr(exc)


def _maybe_save_failure_frame(
    frame, frame_index, frame_record, failure_frame_dir, summary
):
    reason = frame_record.get("failure_reason")
    if not reason:
        return
    reason = str(reason)
    summary["observed"] += 1
    summary["by_reason"][reason] = summary["by_reason"].get(reason, 0) + 1
    if not summary["enabled"] or summary["saved"] >= summary["max_saved"]:
        return
    count = summary["by_reason"][reason]
    if count != 1 and count % summary["sample_stride"] != 0:
        return
    relative_path, error = _save_failure_frame_thumbnail(
        frame, frame_index, reason, failure_frame_dir
    )
    if relative_path is None:
        summary["save_errors"].append({
            "frame_index": int(frame_index),
            "reason": reason,
            "error": error,
        })
        return
    summary["saved"] += 1
    summary["saved_by_reason"][reason] = (
        summary["saved_by_reason"].get(reason, 0) + 1
    )
    frame_record["failure_frame_path"] = relative_path


def build_fusion_records(sync_frames, clock_sync=None):
    """Generate fusion evidence from unique synchronized telemetry samples.

    ``pc_recv_ns`` remains the raw arrival timestamp.  When a fitted
    ``ClockSync`` is supplied, fusion state uses the MCU-tick-derived time so
    batched TCP delivery cannot look like a non-monotonic sensor stream.
    """
    fusion = V1PoseFusion()
    records = []
    seen_ticks = set()
    for sync_frame in sync_frames:
        tick_ms = sync_frame.telemetry.tick_ms
        if tick_ms in seen_ticks:
            continue
        seen_ticks.add(tick_ms)
        timestamp_ns = None
        if clock_sync is not None:
            timestamp_ns = int(round(clock_sync.tick_to_pc_ns(tick_ms)))
        records.append(
            fusion.update(
                sync_frame.pose,
                sync_frame.telemetry,
                timestamp_ns=timestamp_ns,
            )
        )
    return tuple(records)


def write_capture_artifacts(out_dir, poses, telemetry, frame_index=None,
                            diagnostics=None, fusion_records=None,
                            fusion_evidence_source="SYNTHETIC",
                            sync_gate_verdict=None):
    """Publish B3 raw files plus the health/TCP diagnostic evidence."""
    pose_records = [pose.to_dict() for pose in poses]
    telemetry_records = [frame.to_dict() for frame in telemetry]
    frame_records = list(frame_index or ())
    fusion_records = list(fusion_records or ())

    with open(os.path.join(out_dir, "pose.jsonl"), "w", encoding="utf-8") as f:
        for record in pose_records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    with open(os.path.join(out_dir, "telemetry.jsonl"), "w", encoding="utf-8") as f:
        for record in telemetry_records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    with open(os.path.join(out_dir, "frame_index.jsonl"), "w", encoding="utf-8") as f:
        for record in frame_records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    with open(os.path.join(out_dir, "fusion.jsonl"), "w", encoding="utf-8") as f:
        for fusion_record in fusion_records:
            record = fusion_record.to_dict()
            record["imu_yaw_wire_unit"] = "degrees_x100"
            record["imu_yaw_model_unit"] = "radians"
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    imu_evidence = summarize_imu_evidence(
        fusion_records,
        source=fusion_evidence_source,
        sync_gate_verdict=sync_gate_verdict,
    )
    evidence_report = imu_evidence.to_dict()
    evidence_report["imu_yaw_wire_unit"] = "degrees_x100"
    evidence_report["imu_yaw_model_unit"] = "radians"
    with open(os.path.join(out_dir, "imu_evidence.json"), "w", encoding="utf-8") as f:
        json.dump(evidence_report, f, indent=2, ensure_ascii=False)

    camera_motion, motion_evidence = build_camera_motion_evidence(
        poses,
        source=fusion_evidence_source,
        sync_gate_verdict=sync_gate_verdict,
        imu_report=imu_evidence,
    )
    with open(os.path.join(out_dir, "camera_motion.jsonl"), "w",
              encoding="utf-8") as f:
        for motion in camera_motion:
            f.write(json.dumps(motion.to_dict(), ensure_ascii=False,
                               sort_keys=True) + "\n")
    with open(os.path.join(out_dir, "motion_evidence.json"), "w",
              encoding="utf-8") as f:
        json.dump(motion_evidence.to_dict(), f, indent=2,
                  ensure_ascii=False)

    with open(os.path.join(out_dir, "raw_poses.json"), "w", encoding="utf-8") as f:
        json.dump(pose_records, f, ensure_ascii=False)
    with open(os.path.join(out_dir, "raw_telemetry.json"), "w", encoding="utf-8") as f:
        json.dump(telemetry_records, f, ensure_ascii=False)

    diagnostics = diagnostics or {}
    with open(os.path.join(out_dir, "raw_health.json"), "w", encoding="utf-8") as f:
        json.dump(diagnostics.get("health_frames", []), f, indent=2,
                  ensure_ascii=False)
    with open(os.path.join(out_dir, "raw_io.json"), "w", encoding="utf-8") as f:
        json.dump(diagnostics.get("raw_io", {}), f, indent=2,
                  ensure_ascii=False)
    with open(os.path.join(out_dir, "failure_frame_summary.json"),
              "w", encoding="utf-8") as f:
        json.dump(diagnostics.get("failure_frame_summary", {
            "enabled": False,
            "directory": None,
            "max_saved": 0,
            "sample_stride": FAILURE_FRAME_SAMPLE_STRIDE,
            "max_width": FAILURE_FRAME_MAX_WIDTH,
            "jpeg_quality": FAILURE_FRAME_JPEG_QUALITY,
            "saved": 0,
            "observed": 0,
            "by_reason": {},
            "saved_by_reason": {},
            "save_errors": [],
        }), f, indent=2, ensure_ascii=False)


def _status_to_dict(status):
    return {
        "campaign_id": status.campaign_id,
        "run_id": status.run_id,
        "state": status.state,
        "reason": status.reason,
        "tick_ms": int(status.tick_ms),
    }


def evaluate_capture_gate(sync_verdict, actions, outcome):
    """Combine the numerical sync gate with the safety/cleanup gate."""
    if sync_verdict != "PASS":
        return sync_verdict, "sync gate verdict: {}".format(sync_verdict)
    if outcome != "ok":
        return "FAIL", "session outcome is {}".format(outcome)
    required = (
        "stop_sent",
        "stop_confirmed",
        "socket_closed",
        "camera_released",
        "reader_joined",
    )
    missing = [name for name in required if not actions.get(name, False)]
    if missing:
        return "FAIL", "required capture conditions missing: {}".format(
            ", ".join(missing)
        )
    if actions.get("reader_error"):
        return "FAIL", "reader error: {}".format(actions["reader_error"])
    return "PASS", "sync and safety/cleanup gates passed"


def _wait_for_matching_stop(status_cv, statuses, start_index, run_id,
                            timeout_s):
    deadline = time.monotonic() + float(timeout_s)
    with status_cv:
        while True:
            for status in statuses[start_index:]:
                if (
                    status.campaign_id == "sync"
                    and status.run_id == run_id
                    and status.state == "STOPPED"
                    and status.reason == "STOP"
                ):
                    return status
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return None
            status_cv.wait(remaining)


def cleanup_session(sock, cap, run_id, actions, *, wait_for_stop=None,
                    status_cursor=None,
                    stop_confirm_timeout_s=STOP_CONFIRM_TIMEOUT_S,
                    raw_io=None):
    """统一、幂等的清理：STOP（仅当 START 已发出）→ 关 socket → 释放 camera。

    - 仅当 *actions*['start_sent'] 才尝试 STOP；STOP 发送失败记录在
      'stop_error'，但 socket.close 与 cap.release 仍必须执行。
    - 重复调用是幂等的（'cleaned_up' 守卫），动作状态如实记录在 *actions*。
    - *sock* / *cap* 必须是可注入的对象（真 socket/camera 或离线 fake）。
    """
    if actions["cleaned_up"]:
        return
    actions["cleaned_up"] = True

    if actions["start_sent"]:
        actions["stop_attempted"] = True
        stop_cursor = status_cursor() if status_cursor is not None else None
        try:
            stop_cmd = RunCommand("sync", run_id, "STOP").encode()
            sock.sendall(stop_cmd.encode())
            if raw_io is not None:
                raw_io.log_send(stop_cmd.encode())
            actions["stop_sent"] = True
        except BaseException as exc:  # noqa: BLE001 - 清理不得因 STOP 失败而中止
            actions["stop_error"] = repr(exc)

        if actions["stop_sent"] and wait_for_stop is not None:
            try:
                status = wait_for_stop(stop_cursor, run_id,
                                       stop_confirm_timeout_s)
                if status is not None:
                    actions["stop_confirmed"] = True
                    actions["stop_status"] = _status_to_dict(status)
            except BaseException as exc:  # noqa: BLE001 - cleanup continues
                actions["stop_confirm_error"] = repr(exc)

    try:
        sock.close()
        actions["socket_closed"] = True
    except BaseException as exc:    # noqa: BLE001
        actions["close_error"] = repr(exc)
        actions["socket_closed"] = False

    try:
        cap.release()
        actions["camera_released"] = True
    except BaseException as exc:    # noqa: BLE001
        actions["release_error"] = repr(exc)
        actions["camera_released"] = False


def run_sync_capture_session(sock, cap, tracker, run_id,
                             duration_s, wait_timeout_s,
                             stop_confirm_timeout_s=STOP_CONFIRM_TIMEOUT_S,
                             frame_index=None, diagnostics=None,
                             failure_frame_dir=None,
                             max_failure_frame_thumbnails=MAX_FAILURE_FRAME_THUMBNAILS,
                             expected_frame_size=None):
    """START → 等待首帧遥测 → 采集 的生命周期，附带统一幂等清理。

    *sock* / *cap* / *tracker* 由调用方注入（真硬件或离线 fake）。
    返回 (telemetry, poses, actions, outcome)：
      - telemetry: 解析出的 V1TelemetryFrame 列表
      - poses:    采集到的 V1Pose 列表
      - actions:  动作报告（start_sent/stop_attempted/socket_closed/...）
      - outcome:  "ok" | "start_failed" | "no_telemetry_timeout" | "collect_error"

    任何路径（正常 / 超时 / 异常 / START 失败）结束后，cleanup_session 都
    恰好执行一次。测试用 fake socket/camera 驱动本函数，不连接真车。
    """
    actions = _new_action_state()
    telemetry = []
    poses = []
    diagnostics = diagnostics if diagnostics is not None else {}
    failure_frame_summary = _new_failure_frame_summary(
        failure_frame_dir, max_failure_frame_thumbnails
    )
    diagnostics["failure_frame_summary"] = failure_frame_summary
    diagnostics["frame_shape_counts"] = {}
    raw_io = RawIoLogger(None)
    health_frames = []
    diagnostics["health_frames"] = health_frames
    tele_lock = threading.Lock()
    stop_reader = threading.Event()
    status_cv = threading.Condition()
    statuses = []
    status_parse_errors = []
    reader_error = []
    heartbeat_cmd = HeartbeatCommand("sync", run_id).encode().encode("ascii")
    next_heartbeat = None

    def send_heartbeat(force=False):
        """Keep the firmware's one-second lease alive on the capture thread."""
        nonlocal next_heartbeat
        now = time.monotonic()
        if not force and next_heartbeat is not None and now < next_heartbeat:
            return True
        try:
            sock.sendall(heartbeat_cmd)
            raw_io.log_send(heartbeat_cmd)
        except BaseException as exc:  # noqa: BLE001 - cleanup still runs
            actions["heartbeat_error"] = repr(exc)
            return False
        actions["heartbeat_sent"] += 1
        next_heartbeat = time.monotonic() + HEARTBEAT_PERIOD_S
        return True

    def on_telemetry(payload):
        d = decode_telemetry(payload)
        if not d:
            return
        pc_ns = capture_pc_clock_ns()
        pwm = tuple(int(d[k]) for k in ("m1", "m2", "m3", "m4"))
        frame = V1TelemetryFrame(
            sensors=(binarize_sensor(d["s0"]), binarize_sensor(d["s1"]),
                     binarize_sensor(d["s2"]), binarize_sensor(d["s3"])),
            error=float(d["error"]),
            pid_output=float(d["pid_output"]),
            pwm=pwm,
            tick_ms=int(d["tick_ms"]),
            pc_recv_ns=pc_ns,
            yaw_rad=math.radians(float(d["yaw"])),
            imu_yaw_deg_x100=int(d["imu_yaw_deg_x100"]),
            imu_validity=int(d["imu_validity"]),
            imu_validity_known=bool(d["imu_validity_known"]),
            imu_init_status=int(d["imu_init_status"]),
            imu_init_status_known=bool(d["imu_init_status_known"]),
        )
        with tele_lock:
            telemetry.append(frame)

    def on_health(payload):
        d = decode_health(payload)
        if not d:
            return
        record = {
            "frame_ts_s": round(time.time(), 6),
            "pc_recv_ns": capture_pc_clock_ns(),
        }
        record.update({key: int(value) for key, value in d.items()})
        with tele_lock:
            health_frames.append(record)

    def on_status(line):
        try:
            status = parse_status(line)
        except Exception as exc:  # noqa: BLE001 - retain malformed evidence
            with status_cv:
                status_parse_errors.append({"line": line,
                                             "error": repr(exc)})
                status_cv.notify_all()
            return
        with status_cv:
            statuses.append(status)
            status_cv.notify_all()

    def reader_thread():
        """Read mixed binary telemetry and ASCII status frames."""
        parser = MixedStreamParser(on_telemetry=on_telemetry,
                                   on_line=on_status,
                                   on_health=on_health)
        while not stop_reader.is_set():
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            except BaseException as exc:  # noqa: BLE001
                with status_cv:
                    reader_error.append(repr(exc))
                    status_cv.notify_all()
                break
            if not data:
                break
            raw_io.log_recv(data)
            try:
                for byte in data:
                    parser.feed(byte)
            except BaseException as exc:  # noqa: BLE001
                with status_cv:
                    reader_error.append(repr(exc))
                    status_cv.notify_all()
                break

    reader = threading.Thread(target=reader_thread, daemon=True)
    reader.start()

    outcome = "ok"
    try:
        # 发送 START 运行指令
        try:
            start_cmd = RunCommand("sync", run_id, "START").encode()
            sock.sendall(start_cmd.encode())
            raw_io.log_send(start_cmd.encode())
            actions["start_sent"] = True
            print("已发送 START，等待小车运行（遥测流）...")
        except Exception as exc:   # noqa: BLE001 - START 失败也要走清理
            actions["start_error"] = repr(exc)
            outcome = "start_failed"
            return telemetry, poses, actions, outcome
        if not send_heartbeat(force=True):
            outcome = "heartbeat_failed"
            return telemetry, poses, actions, outcome

        # 等待第一帧遥测
        t_wait = time.time()
        while True:
            with tele_lock:
                if telemetry:
                    break
            if not send_heartbeat():
                outcome = "heartbeat_failed"
                return telemetry, poses, actions, outcome
            if time.time() - t_wait > wait_timeout_s:
                print("ERROR: 超时未收到遥测（小车未运行？）")
                outcome = "no_telemetry_timeout"
                return telemetry, poses, actions, outcome
            time.sleep(0.02)
        print(">>> 检测到遥测，开始采集 {}s".format(duration_s))

        # 采集 duration_s 秒
        try:
            start = time.monotonic_ns()
            duration_ns = int(duration_s * 1e9)
            camera_frame_number = 0
            while time.monotonic_ns() - start < duration_ns:
                if not send_heartbeat():
                    outcome = "heartbeat_failed"
                    return telemetry, poses, actions, outcome
                ok, frame = cap.read()
                frame_record = {
                    "frame_index": camera_frame_number,
                    "read_ok": bool(ok),
                    "t_pc_ns": None,
                    "pose_detected": False,
                }
                camera_frame_number += 1
                try:
                    if ok:
                        shape = getattr(frame, "shape", ())
                        if len(shape) < 2:
                            if expected_frame_size is None:
                                shape = (0, 0)
                            else:
                                frame_record["failure_reason"] = (
                                    "camera_frame_shape_unavailable"
                                )
                                actions["collect_error"] = (
                                    "camera frame has no readable shape"
                                )
                                outcome = "camera_frame_dimensions_mismatch"
                                _maybe_save_failure_frame(
                                    frame,
                                    frame_record["frame_index"],
                                    frame_record,
                                    failure_frame_dir,
                                    failure_frame_summary,
                                )
                                return telemetry, poses, actions, outcome
                        frame_height = int(shape[0])
                        frame_width = int(shape[1])
                        frame_record["frame_width"] = frame_width
                        frame_record["frame_height"] = frame_height
                        shape_key = "{}x{}".format(frame_width, frame_height)
                        diagnostics["frame_shape_counts"][shape_key] = (
                            diagnostics["frame_shape_counts"].get(shape_key, 0)
                            + 1
                        )
                        if expected_frame_size is not None:
                            try:
                                validate_frame_dimensions(
                                    (frame_width, frame_height),
                                    expected_frame_size,
                                )
                            except BaseException as exc:
                                frame_record["failure_reason"] = (
                                    "camera_frame_shape_mismatch"
                                )
                                frame_record["expected_frame_width"] = int(
                                    expected_frame_size[0]
                                )
                                frame_record["expected_frame_height"] = int(
                                    expected_frame_size[1]
                                )
                                actions["collect_error"] = repr(exc)
                                outcome = "camera_frame_dimensions_mismatch"
                                _maybe_save_failure_frame(
                                    frame,
                                    frame_record["frame_index"],
                                    frame_record,
                                    failure_frame_dir,
                                    failure_frame_summary,
                                )
                                return telemetry, poses, actions, outcome
                        # Task 4B-4 fix: 帧读取成功立即打时间戳，显式传入 track()，
                        # 不在检测结束后才打采集时间（PoseTracker 默认时间戳在
                        # 检测结束生成）。
                        t_pc_ns = capture_pc_clock_ns()
                        frame_record["t_pc_ns"] = t_pc_ns
                        track_with_diagnostics = getattr(
                            tracker, "track_with_diagnostics", None
                        )
                        if track_with_diagnostics is not None:
                            pose, detector_diagnostics = track_with_diagnostics(
                                frame, t_pc_ns=t_pc_ns
                            )
                            frame_record.update(detector_diagnostics)
                        else:
                            pose = tracker.track(frame, t_pc_ns=t_pc_ns)
                        if pose is not None:
                            frame_record["pose_detected"] = True
                            poses.append(pose)
                        else:
                            _maybe_save_failure_frame(
                                frame,
                                frame_record["frame_index"],
                                frame_record,
                                failure_frame_dir,
                                failure_frame_summary,
                            )
                    else:
                        frame_record["failure_reason"] = "frame_read_failed"
                finally:
                    if frame_index is not None:
                        frame_index.append(frame_record)
        except Exception as exc:   # noqa: BLE001 - 采集异常也要走清理
            actions["collect_error"] = repr(exc)
            outcome = "collect_error"
            return telemetry, poses, actions, outcome
    finally:
        def status_cursor():
            with status_cv:
                return len(statuses)

        def wait_for_stop(cursor, target_run_id, timeout_s):
            return _wait_for_matching_stop(
                status_cv, statuses, cursor if cursor is not None else 0,
                target_run_id, timeout_s)

        # 统一幂等清理：无论 outcome 是什么都恰好执行一次。
        cleanup_session(
            sock, cap, run_id, actions,
            wait_for_stop=wait_for_stop,
            status_cursor=status_cursor,
            stop_confirm_timeout_s=stop_confirm_timeout_s,
            raw_io=raw_io,
        )
        stop_reader.set()
        try:
            reader.join(timeout=READER_JOIN_TIMEOUT_S)
            actions["reader_joined"] = not reader.is_alive()
            if not actions["reader_joined"]:
                actions["reader_join_error"] = "reader thread did not quiesce"
        except BaseException as exc:  # noqa: BLE001 - preserve primary outcome
            actions["reader_join_error"] = repr(exc)
        with status_cv:
            actions["status_events"] = [_status_to_dict(status)
                                         for status in statuses]
            actions["status_parse_errors"] = list(status_parse_errors)
            if reader_error:
                actions["reader_error"] = reader_error[-1]
        diagnostics["health_frames"] = list(health_frames)
        diagnostics["health"] = compute_health_summary(health_frames)
        diagnostics["raw_io"] = raw_io.write()

    return telemetry, poses, actions, outcome


def build_sync_report(*, host, duration_s, run_id, camera_mode, actions,
                      outcome, n_poses, n_telemetry, clock, residuals, sync,
                      calibration_evidence=None, diagnostics=None):
    """Build the auditable 4B-4 report without touching hardware or files."""
    actual_camera = dict(camera_mode)
    report = {
        "schema_version": 1,
        "task": "4B-4",
        "host": host,
        "duration_s": float(duration_s),
        "run_id": run_id,
        "camera": {
            "requested": {
                "width": CAMERA_WIDTH,
                "height": CAMERA_HEIGHT,
                "fps": CAMERA_FPS,
                "fourcc": "MJPG",
            },
            "actual": actual_camera,
        },
        "actions": dict(actions),
        "session_outcome": outcome,
        "telemetry_yaw_unit": "radian",
        "n_poses": int(n_poses),
        "n_telemetry": int(n_telemetry),
        "calibration": dict(calibration_evidence or {}),
        "diagnostics": {
            "health": dict((diagnostics or {}).get("health", {})),
            "raw_health_file": "raw_health.json",
            "raw_io_file": "raw_io.json",
        },
        "clock": {
            "a": float(clock["a"]),
            "b": float(clock["b"]),
            "n_samples": int(clock["n_samples"]),
            "fit": "fit_batched",
            "residual_rms_ns": float(residuals["rms_ns"]),
            "residual_max_ns": float(residuals["max_ns"]),
        },
    }
    for key in (
        "coverage", "p95_time_diff_ns", "tolerance_ns", "n_sync_frames",
        "common_interval_start_ns", "common_interval_end_ns",
        "common_interval_duration_ns", "n_common_poses",
        "telemetry_interval_max_ns", "telemetry_interval_p95_ns",
        "n_telemetry_distinct", "max_telemetry_reuse", "verdict",
        "gate_reason",
    ):
        report[key] = sync[key]
    sync_gate_verdict = sync["verdict"]
    final_verdict, final_reason = evaluate_capture_gate(
        sync_gate_verdict, actions, outcome)
    report["sync_gate_verdict"] = sync_gate_verdict
    report["verdict"] = final_verdict
    report["gate_reason"] = final_reason
    return report


def build_session_failure_report(*, host, duration_s, run_id, camera_mode,
                                 actions, outcome, reason, n_poses,
                                 n_telemetry):
    """Build a non-passing report for failures before clock fitting."""
    return {
        "schema_version": 1,
        "task": "4B-4",
        "host": host,
        "duration_s": float(duration_s),
        "run_id": run_id,
        "camera": {
            "requested": {
                "width": CAMERA_WIDTH,
                "height": CAMERA_HEIGHT,
                "fps": CAMERA_FPS,
                "fourcc": "MJPG",
            },
            "actual": (dict(camera_mode) if camera_mode is not None else None),
        },
        "actions": dict(actions),
        "session_outcome": outcome,
        "failure_reason": reason,
        "verdict": "FAIL",
        "telemetry_yaw_unit": "radian",
        "n_poses": int(n_poses),
        "n_telemetry": int(n_telemetry),
        "missing_artifacts": list(B3_RAW_FILENAMES),
    }


def write_session_failure_report(out_dir, *, host, duration_s, run_id,
                                 camera_mode, actions, outcome, reason,
                                 n_poses, n_telemetry):
    report = build_session_failure_report(
        host=host,
        duration_s=duration_s,
        run_id=run_id,
        camera_mode=camera_mode,
        actions=actions,
        outcome=outcome,
        reason=reason,
        n_poses=n_poses,
        n_telemetry=n_telemetry,
    )
    with open(os.path.join(out_dir, "sync_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report


def connect_car(host, port, socket_factory=None):
    """Connect with bounded timeouts and close the socket on connect failure."""
    factory = socket_factory or socket.socket
    sock = factory(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(3.0)
        sock.connect((host, port))
        sock.settimeout(0.1)
    except BaseException:
        try:
            sock.close()
        except BaseException:
            pass
        raise
    return sock


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(manifest_path, value):
    path = Path(value)
    if not path.is_absolute():
        path = Path(manifest_path).parent / path
    path = path.resolve()
    if not path.is_relative_to(_WORKSPACE_ROOT):
        raise ValueError("calibration input must stay inside the workspace")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _load_calibration(manifest_path):
    """Load an explicitly selected calibration manifest and its evidence."""
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(str(manifest_path))
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported calibration manifest schema")

    intrinsics_path = _manifest_path(
        manifest_path, manifest["intrinsics_path"]
    )
    profile_path = _manifest_path(manifest_path, manifest["profile_path"])
    with open(intrinsics_path, encoding="utf-8") as f:
        intrinsics_data = json.load(f)
    with open(profile_path, encoding="utf-8") as f:
        profile = json.load(f)

    calibration_data = dict(
        intrinsics_data.get("calibration", intrinsics_data)
    )
    dist_coeffs = calibration_data.get("dist_coeffs")
    if (
        isinstance(dist_coeffs, list)
        and len(dist_coeffs) == 1
        and isinstance(dist_coeffs[0], list)
    ):
        calibration_data["dist_coeffs"] = dist_coeffs[0]
    calibration_data.setdefault(
        "reprojection_error_rms",
        calibration_data.get("reprojection_error_rms_px"),
    )
    calibration_data.setdefault(
        "reprojection_error_p95",
        calibration_data.get("reprojection_error_p95_px"),
    )
    transform_data = profile.get("ground_transform") or profile.get("homography")
    if not isinstance(transform_data, dict):
        raise ValueError("calibration profile has no ground transform")
    calib = CameraCalibration.from_dict(calibration_data)
    homography = HomographyTransform.from_dict(transform_data)
    workspace = _WORKSPACE_ROOT
    evidence = {
        "manifest_path": manifest_path.relative_to(workspace).as_posix(),
        "manifest_sha256": _sha256_file(manifest_path),
        "intrinsics_path": intrinsics_path.relative_to(workspace).as_posix(),
        "intrinsics_sha256": _sha256_file(intrinsics_path),
        "profile_path": profile_path.relative_to(workspace).as_posix(),
        "profile_sha256": _sha256_file(profile_path),
        "calibration_id": profile.get("calibration_id"),
        "quality": profile.get("quality"),
        "camera_model": profile.get("camera", {}).get("model"),
        "image_size": profile.get("camera", {}).get("image_size"),
    }
    return calib, homography, evidence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.110.236")
    ap.add_argument("--port", type=int, default=8888)
    ap.add_argument("--camera", default="1")
    ap.add_argument("--duration", type=float, default=12.0)
    ap.add_argument("--wait-timeout", type=float, default=30.0)
    ap.add_argument("--calibration-manifest", required=True)
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    run_id = make_run_id()
    out_dir = resolve_run_output_dir(args.out, run_id, OUTPUT_FILENAMES)
    print("run_id:", run_id, "->", out_dir)

    try:
        calib, hom, calibration_evidence = _load_calibration(
            args.calibration_manifest
        )
    except BaseException as exc:
        actions = _new_action_state()
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=None,
            actions=actions,
            outcome="calibration_setup_failed",
            reason=repr(exc),
            n_poses=0,
            n_telemetry=0,
        )
        print("ERROR: calibration setup failed: {}".format(exc))
        return 1
    tracker = PoseTracker(calib, hom, tag_id=0, detect_scales=(1.0, 2.0, 3.0))

    src = int(args.camera) if str(args.camera).isdigit() else args.camera
    try:
        cap, actual_w, actual_h = open_capture_camera(src)
    except BaseException as exc:
        actions = _new_action_state()
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=None,
            actions=actions,
            outcome="camera_setup_failed",
            reason=repr(exc),
            n_poses=0,
            n_telemetry=0,
        )
        print("ERROR: camera setup failed: {}".format(exc))
        return 1

    # Task 4B-4 fix: cap.set() 不能当作成功证据——读取实际尺寸并 fail closed。
    try:
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        camera_mode = read_camera_mode(cap, src, actual_w, actual_h)
    except BaseException as exc:
        actions = _new_action_state()
        try:
            cap.release()
            actions["camera_released"] = True
        except BaseException as cleanup_exc:  # noqa: BLE001
            actions["release_error"] = repr(cleanup_exc)
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=None,
            actions=actions,
            outcome="camera_probe_failed",
            reason=repr(exc),
            n_poses=0,
            n_telemetry=0,
        )
        print("ERROR: camera probe failed: {}".format(exc))
        return 1
    print("camera actual frame size:", (actual_w, actual_h),
          "calibration image_size:", calib.image_size)
    try:
        validate_frame_dimensions((actual_w, actual_h), calib.image_size)
    except BaseException as exc:
        actions = _new_action_state()
        try:
            cap.release()
            actions["camera_released"] = True
        except BaseException as cleanup_exc:  # noqa: BLE001
            actions["release_error"] = repr(cleanup_exc)
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=camera_mode,
            actions=actions,
            outcome="camera_dimensions_mismatch",
            reason=repr(exc),
            n_poses=0,
            n_telemetry=0,
        )
        print("ERROR: {0}".format(exc))
        return 1
    if (
        camera_mode["fourcc"] != "MJPG"
        or not math.isfinite(camera_mode["fps"])
        or abs(camera_mode["fps"] - CAMERA_FPS) > 0.5
    ):
        actions = _new_action_state()
        try:
            cap.release()
            actions["camera_released"] = True
        except BaseException as cleanup_exc:  # noqa: BLE001
            actions["release_error"] = repr(cleanup_exc)
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=camera_mode,
            actions=actions,
            outcome="camera_mode_mismatch",
            reason="actual camera mode does not match 1920x1080 MJPG/30fps",
            n_poses=0,
            n_telemetry=0,
        )
        print("ERROR: camera mode mismatch: {}".format(camera_mode))
        return 1

    print("connecting to car {}:{} ...".format(args.host, args.port))
    try:
        sock = connect_car(args.host, args.port)
    except BaseException as exc:  # noqa: BLE001 - publish connection failure
        actions = _new_action_state()
        try:
            cap.release()
            actions["camera_released"] = True
        except BaseException as cleanup_exc:  # noqa: BLE001
            actions["release_error"] = repr(cleanup_exc)
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=camera_mode,
            actions=actions,
            outcome="connect_failed",
            reason=repr(exc),
            n_poses=0,
            n_telemetry=0,
        )
        print("ERROR: car connection failed: {}".format(exc))
        return 1

    # 采集生命周期（START→等待→采集→统一清理）由 session 函数负责。
    frame_index = []
    diagnostics = {}
    telemetry, poses, actions, outcome = run_sync_capture_session(
        sock, cap, tracker, run_id, args.duration, args.wait_timeout,
        frame_index=frame_index, diagnostics=diagnostics,
        failure_frame_dir=Path(out_dir) / FAILURE_FRAME_DIRNAME,
        expected_frame_size=(CAMERA_WIDTH, CAMERA_HEIGHT))

    # 动作状态报告：START 失败时不假称已 STOP。
    print("cleanup actions:", {k: v for k, v in actions.items()})

    if outcome in (
        "start_failed", "heartbeat_failed", "no_telemetry_timeout",
        "collect_error", "camera_frame_dimensions_mismatch",
    ):
        write_capture_artifacts(out_dir, poses, telemetry, frame_index,
                                diagnostics)
        reason = (actions.get("start_error") or actions.get("collect_error")
                  or outcome)
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=camera_mode,
            actions=actions,
            outcome=outcome,
            reason=reason,
            n_poses=len(poses),
            n_telemetry=len(telemetry),
        )
        print("ERROR: session outcome={0}: {1}".format(outcome, reason))
        return 1

    print("采集完成: 位姿 {} 帧, 遥测 {} 帧".format(len(poses), len(telemetry)))
    if len(poses) < 20 or len(telemetry) < 20:
        reason = "insufficient capture data"
        write_capture_artifacts(out_dir, poses, telemetry, frame_index,
                                diagnostics)
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=camera_mode,
            actions=actions,
            outcome="insufficient_data",
            reason=reason,
            n_poses=len(poses),
            n_telemetry=len(telemetry),
        )
        print("ERROR: 数据不足")
        return 1

    # 拟合时钟（批量投递 → fit_batched）
    try:
        clock = ClockSync()
        for t in telemetry:
            clock.add_sample(t.tick_ms, t.pc_recv_ns)
        clock.fit_batched()
        a, b = clock.params()
        residuals = clock.fit_residuals()
    except BaseException as exc:  # noqa: BLE001 - publish a structured failure
        write_capture_artifacts(out_dir, poses, telemetry, frame_index,
                                diagnostics)
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=camera_mode,
            actions=actions,
            outcome="clock_fit_failed",
            reason=repr(exc),
            n_poses=len(poses),
            n_telemetry=len(telemetry),
        )
        print("ERROR: ClockSync failed: {}".format(exc))
        return 1
    print("ClockSync(batched): pc_ns = {:.3f} * tick + {:.0f}, resid_rms={:.0f}ns".format(
        a, b, residuals["rms_ns"]))

    # 对齐（共同区间语义 + 全量 p95 + 诊断指标）
    try:
        ds = build_synchronized_dataset(poses, telemetry, clock, TOLERANCE_NS,
                                        model_version="1.0.0")
        gate = evaluate_sync_gate(ds)
        fusion_records = build_fusion_records(ds.sync_frames, clock)
    except BaseException as exc:  # noqa: BLE001 - publish a structured failure
        write_capture_artifacts(out_dir, poses, telemetry, frame_index,
                                diagnostics)
        write_session_failure_report(
            out_dir,
            host=args.host,
            duration_s=args.duration,
            run_id=run_id,
            camera_mode=camera_mode,
            actions=actions,
            outcome="dataset_build_failed",
            reason=repr(exc),
            n_poses=len(poses),
            n_telemetry=len(telemetry),
        )
        print("ERROR: synchronized dataset failed: {}".format(exc))
        return 1
    print("== 4B-4 同步验证 (Task 4B-4 fix) ==")
    print("共同区间: {:.1f}ms .. {:.1f}ms (时长 {:.0f}ms)".format(
        ds.common_interval_start_ns / 1e6, ds.common_interval_end_ns / 1e6,
        ds.common_interval_duration_ns / 1e6))
    print("共同区间 pose 数: {} / {}".format(ds.n_common_poses, len(poses)))
    print("匹配覆盖率: {:.1f}%  (>=95%: {})".format(100 * ds.coverage,
        ds.coverage >= 0.95))
    print("p95 时间差(全部最近距离): {:.1f} ms  (<={} ms: {})".format(
        ds.p95_time_diff_ns / 1e6, TOLERANCE_NS / 1e6,
        ds.p95_time_diff_ns <= TOLERANCE_NS))
    print("遥测间隔 max/p95: {:.1f}/{:.1f} ms".format(
        ds.telemetry_interval_max_ns / 1e6, ds.telemetry_interval_p95_ns / 1e6))
    print("匹配用不同遥测帧: {}  最大复用: {}".format(
        ds.n_telemetry_distinct, ds.max_telemetry_reuse))
    print("时钟拟合残差 RMS: {:.1f} ms".format(ds.clock_fit_residual_rms_ns / 1e6))
    print("VERDICT: {}".format(gate.verdict))

    report = build_sync_report(
        host=args.host,
        duration_s=args.duration,
        run_id=run_id,
        camera_mode=camera_mode,
        actions=actions,
        outcome=outcome,
        n_poses=len(poses),
        n_telemetry=len(telemetry),
        clock={"a": a, "b": b, "n_samples": len(telemetry)},
        residuals=residuals,
        sync={
            "coverage": ds.coverage,
            "p95_time_diff_ns": ds.p95_time_diff_ns,
            "tolerance_ns": TOLERANCE_NS,
            "n_sync_frames": len(ds.sync_frames),
            "common_interval_start_ns": ds.common_interval_start_ns,
            "common_interval_end_ns": ds.common_interval_end_ns,
            "common_interval_duration_ns": ds.common_interval_duration_ns,
            "n_common_poses": ds.n_common_poses,
            "telemetry_interval_max_ns": ds.telemetry_interval_max_ns,
            "telemetry_interval_p95_ns": ds.telemetry_interval_p95_ns,
            "n_telemetry_distinct": ds.n_telemetry_distinct,
            "max_telemetry_reuse": ds.max_telemetry_reuse,
            "verdict": gate.verdict,
            "gate_reason": gate.reason,
        },
        calibration_evidence=calibration_evidence,
        diagnostics=diagnostics,
    )
    with open(os.path.join(out_dir, "sync_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    # 保存原始数据（独立 run_id 目录，不覆盖）
    write_capture_artifacts(
        out_dir,
        poses,
        telemetry,
        frame_index,
        diagnostics,
        fusion_records=fusion_records,
        fusion_evidence_source="REAL_SYNC",
        sync_gate_verdict=gate.verdict,
    )
    print("report:", os.path.join(out_dir, "sync_report.json"))
    return 0 if report["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
