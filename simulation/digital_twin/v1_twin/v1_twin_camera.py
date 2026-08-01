"""CameraSource 抽象 + OpenCV 实现 + Gate 0 验证 (Task 4B-1)。

帧率/丢帧统计逻辑与硬件解耦：`compute_camera_stats()` 是纯函数，可离线测试；
`OpenCVCameraSource` 通过 `cv2.VideoCapture` 接入 USB / DroidCam / MJPEG 实时流。

Gate 0 标准（纲领 §6b / §6i G1）：
连续 10 分钟录制，有效帧率 >= 20 fps，drop_rate <= 5%，时间戳严格单调。

**帧时间戳时钟：** 使用 `time.perf_counter_ns()`（Windows 上为 QPC，分辨率约
100 ns），而非 `time.monotonic_ns()`。实测本机 `monotonic_ns()` 量化约
15.6 ms（GetTickCount64），相邻调用会返回相同值，无法满足帧时间戳的
严格单调要求（30fps 帧间隔仅 ~33ms）。`perf_counter_ns()` 同为单调 PC
时钟（单位 ns），分辨率足以保证帧间严格递增。此差异已在 4B-1 handoff 中
记录，供用户决定是否同步修订 4B-0 schema 的时钟约定文档。
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import cv2
except ImportError:  # pragma: no cover — 无 OpenCV 时仅抽象/统计可用
    cv2 = None  # type: ignore[assignment]


class CameraError(RuntimeError):
    """摄像头源错误。"""


@dataclass(frozen=True)
class CameraStats:
    """Gate 0 统计结果。"""
    duration_s: float
    frame_count: int
    effective_fps: float
    drop_rate_pct: float
    timestamps_monotonic: bool
    dropped_frames: int
    expected_frames: int
    nominal_period_ms: float = 0.0   # 丢帧检测所用标称周期（均值间隔）
    resolution_match: bool = True    # 实际分辨率是否与请求一致
    actual_width: int = 0            # 实际协商宽度
    actual_height: int = 0           # 实际协商高度
    requested_width: int = 0         # 请求宽度
    requested_height: int = 0        # 请求高度
    invalid_content_frames: int = 0  # 正式计时区间内无效内容帧数
    warmup_frames_discarded: int = 0 # warm-up 阶段丢弃帧数
    duplicate_rate_pct: float = 0.0  # 连续重复帧占比


# ============================================================
# 抽象
# ============================================================


class CameraSource(ABC):
    """摄像头源抽象。read() 返回 (frame, timestamp_ns, ok)。"""

    @abstractmethod
    def start(self) -> None:
        """打开摄像头源。"""

    @abstractmethod
    def stop(self) -> None:
        """关闭摄像头源。"""

    @abstractmethod
    def read(self) -> Tuple[Any, int, bool]:
        """读取一帧。

        返回 (frame, timestamp_ns, ok)：
        - frame: 图像帧（OpenCV 下为 np.ndarray；ok=False 时为 None）
        - timestamp_ns: `time.perf_counter_ns()` 读取时刻（单调 PC 时钟，ns）
        - ok: 是否取得新帧
        """


class OpenCVCameraSource(CameraSource):
    """基于 cv2.VideoCapture 的实现，支持设备索引或 MJPEG URL。"""

    def __init__(
        self,
        source: Any = 0,
        name: str = "opencv",
        width: int = 0,
        height: int = 0,
    ):
        self._source = source
        self._name = name
        self._width = width
        self._height = height
        self._cap: Any = None

    def start(self) -> None:
        if cv2 is None:
            raise CameraError("OpenCV (cv2) is not importable")
        cap = cv2.VideoCapture(self._source)
        if not cap.isOpened():
            raise CameraError("cannot open camera source: {0!r}".format(self._source))
        # DroidCam 虚拟摄像头默认 640x480 非等比缩放，需请求原生 1280x720
        if self._width and self._height:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap = cap

    def stop(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read(self) -> Tuple[Any, int, bool]:
        if self._cap is None:
            raise CameraError("camera not started; call start() first")
        ok, frame = self._cap.read()
        return frame, time.perf_counter_ns(), bool(ok)


# ============================================================
# 统计逻辑（纯函数，无硬件依赖）
# ============================================================


def compute_camera_stats(
    timestamps_ns: List[int],
    nominal_period_ns: int,
    duration_s: float,
) -> CameraStats:
    """从时间戳序列计算帧率 / 丢帧 / 单调性统计。

    丢帧判定：相邻时间戳间隔 > 1.5 × 标称周期的缺口，按缺口中缺失的
    标称帧数计为 dropped_frames。
    """
    n = len(timestamps_ns)
    nominal_period_ms = nominal_period_ns / 1e6
    if n == 0:
        return CameraStats(
            duration_s=duration_s, frame_count=0, effective_fps=0.0,
            drop_rate_pct=0.0, timestamps_monotonic=True,
            dropped_frames=0, expected_frames=0,
            nominal_period_ms=nominal_period_ms,
        )

    monotonic = all(
        timestamps_ns[i] < timestamps_ns[i + 1] for i in range(n - 1)
    )

    if n >= 2:
        span_ns = timestamps_ns[-1] - timestamps_ns[0]
        effective_fps = ((n - 1) / (span_ns / 1e9)) if span_ns > 0 else 0.0
    else:
        effective_fps = (
            (1.0 / (nominal_period_ns / 1e9)) if nominal_period_ns > 0 else 0.0
        )

    dropped = 0
    if nominal_period_ns > 0:
        gap_threshold = nominal_period_ns * 1.5
        for i in range(n - 1):
            gap = timestamps_ns[i + 1] - timestamps_ns[i]
            if gap > gap_threshold:
                missing = int(round(gap / nominal_period_ns)) - 1
                dropped += max(0, missing)

    expected = n + dropped
    drop_rate_pct = (dropped / expected) * 100.0 if expected > 0 else 0.0

    return CameraStats(
        duration_s=duration_s,
        frame_count=n,
        effective_fps=effective_fps,
        drop_rate_pct=drop_rate_pct,
        timestamps_monotonic=monotonic,
        dropped_frames=dropped,
        expected_frames=expected,
        nominal_period_ms=nominal_period_ms,
    )


# ============================================================
# 内容有效性检查（纯函数，无硬件依赖）
# ============================================================

import hashlib
import numpy as np


def _frame_hash(frame: Any) -> str:
    """帧内容的快速哈希（用于重复检测）。"""
    if frame is None:
        return ""
    # 非 numpy 帧用字符串表示做哈希
    if not isinstance(frame, np.ndarray):
        return hashlib.md5(str(frame).encode()).hexdigest()
    # 降采样到 1/4 尺寸加速哈希（足够检测冻结帧）
    small = frame[::4, ::4] if frame.ndim >= 2 else frame
    return hashlib.md5(small.tobytes()).hexdigest()


def is_frame_black(frame: Any, mean_threshold: float = 10.0) -> bool:
    """检测帧是否全黑或近乎全黑（模拟 DroidCam 启动画面）。

    *mean_threshold*: 各通道均值低于此值视为黑帧。
    返回 True 表示该帧无效（全黑/启动画面）。
    非 numpy 数组的帧默认视为有效（无法做像素级判断）。
    """
    if frame is None:
        return True
    # 非 numpy 帧（如 FakeCamera 的字符串标记）无法判断，视为有效
    if not isinstance(frame, np.ndarray):
        return False
    try:
        mean_val = float(np.mean(frame))
        return mean_val < mean_threshold
    except Exception:
        return True  # 无法读取内容的帧视为无效


def is_frame_stale(frame: Any, previous_frame_hash: Optional[str]) -> bool:
    """检测帧是否与前一帧完全相同（冻结/卡死）。

    返回 True 表示该帧是重复帧。
    若 *previous_frame_hash* 为 None（第一帧），返回 False。
    非 numpy 帧不做逐像素比较，默认返回 False。
    """
    if previous_frame_hash is None:
        return False
    if frame is None:
        return True
    if not isinstance(frame, np.ndarray):
        return False  # 非 numpy 帧不做像素级重复检测
    return _frame_hash(frame) == previous_frame_hash


# ============================================================
# Gate 0 验证
# ============================================================


def _save_frame(out_dir: str, name: str, frame: Any) -> str:
    if cv2 is None:
        return ""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    try:
        # 用 imencode + Python 写入，而不是 cv2.imwrite：
        # cv2.imwrite 在 Windows 上无法处理含非 ASCII 字符的路径（会静默失败）。
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            return ""
        with open(path, "wb") as f:
            f.write(encoded.tobytes())
    except Exception:
        return ""
    return path


def verify_gate0(
    source: Any = 0,
    duration_s: float = 600.0,
    out_dir: str = ".embeddedskills/build/v1_task4b1",
    save_frames: bool = True,
    width: int = 0,
    height: int = 0,
    warmup_required: bool = True,
) -> CameraStats:
    """连续录制 *duration_s* 秒并返回统计结果。

    *source* 可以是原始源（int 设备索引 / MJPEG URL），此时内部创建
    ``OpenCVCameraSource``；也可以是已实现的 ``CameraSource`` 实例
    （便于测试注入 Fake）。*width*/*height* 指定后请求该分辨率
    （DroidCam 需 1280x720 原生）。

    *warmup_required* 启用时，在正式计时前丢弃全黑/近乎黑/连续重复帧，
    直到连续出现内容有效的帧后进入计时区间。
    """
    if isinstance(source, CameraSource):
        cam: CameraSource = source
    else:
        cam = OpenCVCameraSource(source, width=width, height=height)

    cam.start()

    # --- 分辨率检测 ---
    actual_w, actual_h = 0, 0
    # 对于 OpenCVCameraSource，从底层 cv2.VideoCapture 获取实际分辨率
    if isinstance(cam, OpenCVCameraSource) and cam._cap is not None:
        actual_w = int(cam._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cam._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # 对于注入的 Fake（ContentFakeCamera），读取其属性
    if hasattr(cam, "actual_width") and hasattr(cam, "actual_height"):
        actual_w = cam.actual_width  # type: ignore[attr-defined]
        actual_h = cam.actual_height  # type: ignore[attr-defined]
    resolution_ok = True
    if width > 0 and height > 0:
        resolution_ok = (actual_w == width and actual_h == height)

    # --- warm-up 阶段 ---
    warmup_discarded = 0
    prev_hash: Optional[str] = None
    consecutive_valid = 0
    stale_streak = 0
    WARMUP_CONSECUTIVE_REQUIRED = 3  # 需要连续 N 帧内容有效才进入计时
    STALE_THRESHOLD = 5              # 连续 N 帧哈希相同才判定为冻结

    if warmup_required:
        warmup_failures = 0
        while True:
            frame, ts, ok = cam.read()
            if not ok:
                warmup_discarded += 1
                warmup_failures += 1
                if warmup_failures >= 30:
                    break
                continue
            warmup_failures = 0
            black = is_frame_black(frame)
            fhash = _frame_hash(frame)
            # 非 numpy 帧不做像素级重复检测（字符串标记等）
            is_stale = (
                isinstance(frame, np.ndarray)
                and prev_hash is not None
                and fhash == prev_hash
            )

            if is_stale:
                stale_streak += 1
            else:
                stale_streak = 0

            prev_hash = fhash

            if black:
                # 黑帧立即丢弃
                warmup_discarded += 1
                consecutive_valid = 0
            elif stale_streak >= STALE_THRESHOLD:
                # 冻结：连续 N 帧相同 → 丢弃，重置
                warmup_discarded += 1
                consecutive_valid = 0
            elif is_stale:
                # 相同但未达阈值：中性帧（不计数，不丢弃）
                pass
            else:
                # 内容变化的有效帧
                consecutive_valid += 1

            if consecutive_valid >= WARMUP_CONSECUTIVE_REQUIRED:
                break

    # --- 正式计时区间 ---
    timestamps: List[int] = []
    saved_frames: Dict[str, str] = {}
    invalid_content = 0
    duplicate_count = 0
    total_official_frames = 0
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 30
    prev_hash = None
    t_start = time.perf_counter()
    try:
        while True:
            frame, ts, ok = cam.read()
            if not ok:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    break
                continue
            consecutive_failures = 0
            elapsed = time.perf_counter() - t_start
            if elapsed >= duration_s:
                break

            total_official_frames += 1

            # 内容有效性检查（统计但不丢弃——保持 honest 统计）
            if is_frame_black(frame):
                invalid_content += 1
            elif isinstance(frame, np.ndarray):
                fhash = _frame_hash(frame)
                if prev_hash is not None and fhash == prev_hash:
                    duplicate_count += 1
                prev_hash = fhash
            # 非 numpy 帧不做像素级重复检测

            timestamps.append(ts)

            if save_frames and not is_frame_black(frame):
                if not saved_frames:
                    saved_frames["frame_start.png"] = _save_frame(
                        out_dir, "frame_start.png", frame
                    )
                if elapsed >= duration_s * 0.5 and "frame_mid.png" not in saved_frames:
                    saved_frames["frame_mid.png"] = _save_frame(
                        out_dir, "frame_mid.png", frame
                    )
                if elapsed >= duration_s * 0.9 and "frame_end.png" not in saved_frames:
                    saved_frames["frame_end.png"] = _save_frame(
                        out_dir, "frame_end.png", frame
                    )
    finally:
        cam.stop()

    actual_duration = time.perf_counter() - t_start
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
    if gaps:
        nominal_period_ns = sum(gaps) // len(gaps)
    else:
        nominal_period_ns = int(1e9 / 30)
    stats = compute_camera_stats(timestamps, nominal_period_ns, actual_duration)

    dup_rate = (duplicate_count / total_official_frames * 100.0) if total_official_frames > 0 else 0.0

    # 返回扩展的 CameraStats（用 object.__setattr__ 绕过 frozen）
    object.__setattr__(stats, "resolution_match", resolution_ok)
    object.__setattr__(stats, "actual_width", actual_w)
    object.__setattr__(stats, "actual_height", actual_h)
    object.__setattr__(stats, "requested_width", width)
    object.__setattr__(stats, "requested_height", height)
    object.__setattr__(stats, "invalid_content_frames", invalid_content)
    object.__setattr__(stats, "warmup_frames_discarded", warmup_discarded)
    object.__setattr__(stats, "duplicate_rate_pct", round(dup_rate, 3))
    return stats


# ============================================================
# CLI
# ============================================================


def _main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="v1_twin 摄像头 Gate 0 验证（连续录制 + 统计）"
    )
    parser.add_argument("--gate0", action="store_true", help="运行 Gate 0 验证")
    parser.add_argument(
        "--source", default="0", help="OpenCV 源：设备索引或 MJPEG URL"
    )
    parser.add_argument(
        "--duration", type=float, default=600.0, help="录制秒数（默认 600 = 10 分钟）"
    )
    parser.add_argument(
        "--outdir", default=".embeddedskills/build/v1_task4b1", help="输出目录"
    )
    parser.add_argument(
        "--width", type=int, default=0, help="请求帧宽（DroidCam 用 1280）"
    )
    parser.add_argument(
        "--height", type=int, default=0, help="请求帧高（DroidCam 用 720）"
    )
    args = parser.parse_args(argv)

    if not args.gate0:
        parser.print_help()
        return 0

    source: Any = args.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    stats = verify_gate0(
        source=source, duration_s=args.duration, out_dir=args.outdir,
        width=args.width, height=args.height,
    )
    fps = stats.effective_fps
    drop = stats.drop_rate_pct
    mono = stats.timestamps_monotonic
    passed = fps >= 20.0 and drop <= 5.0 and mono

    # 综合判断（含分辨率匹配）
    resolution_ok = stats.resolution_match
    warmup_ok = stats.warmup_frames_discarded >= 0   # warm-up 完成
    content_ok = stats.invalid_content_frames == 0   # 正式区间无无效帧
    all_passed = passed and resolution_ok and content_ok

    report = {
        "gate": "G1",
        "source": args.source,
        "duration_s": round(stats.duration_s, 3),
        "frame_count": stats.frame_count,
        "effective_fps": round(fps, 2),
        "nominal_period_ms": round(stats.nominal_period_ms, 3),
        "drop_rate_pct": round(drop, 3),
        "timestamps_monotonic": mono,
        "dropped_frames": stats.dropped_frames,
        "expected_frames": stats.expected_frames,
        "drop_detection": "gap>1.5x mean-interval",
        "resolution": {
            "requested": f"{args.width}x{args.height}" if args.width else "default",
            "actual": f"{stats.actual_width}x{stats.actual_height}",
            "match": resolution_ok,
        },
        "warmup": {
            "frames_discarded": stats.warmup_frames_discarded,
        },
        "content_validity": {
            "invalid_frames": stats.invalid_content_frames,
            "duplicate_rate_pct": stats.duplicate_rate_pct,
        },
        "verdict": "PASS" if all_passed else "FAIL",
        "verdict_details": {
            "fps_gate": passed,
            "resolution_gate": resolution_ok,
            "content_gate": content_ok,
        },
    }
    os.makedirs(args.outdir, exist_ok=True)
    report_path = os.path.join(args.outdir, "gate0_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(
        "Gate 0: fps={0:.2f} (>=20) | drop_rate={1:.3f}% (<=5%) | "
        "monotonic={2} | resolution={3}x{4} match={5} | invalid_content={6} | "
        "warmup_discarded={7} -> {8}".format(
            fps, drop, mono,
            stats.actual_width, stats.actual_height, resolution_ok,
            stats.invalid_content_frames, stats.warmup_frames_discarded,
            report["verdict"])
    )
    print("report: {0}".format(report_path))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(_main())
