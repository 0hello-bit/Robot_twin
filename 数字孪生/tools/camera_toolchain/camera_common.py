"""相机工具链公共模块。

- 摄像头索引自动检测 + 配置持久化（DirectShow 索引热插拔会漂移，见 2026-08-03 记录：
  C960 曾为 2，重插后为 1）。
- unicode 路径图像 IO（OpenCV imread/imwrite 对非 ASCII 路径静默失败，须用字节流）。

所有工具统一 `import camera_common as cc`，用 `cc.get_camera_index()` 取索引。
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera_config.json")
DEFAULT_BACKEND = cv2.CAP_DSHOW
DEFAULT_FPS = 30.0
DEFAULT_FOURCC = "MJPG"


def detect_camera_indices(max_index: int = 6, min_ok: int = 3) -> list:
    """扫描能实际取到有效帧的摄像头索引。

    仅 ``isOpened()`` 不算检测成功：必须用 DSHOW 打开并连续读帧，验证分辨率
    有效、内容非纯黑、成功帧数达标。避免把"能打开但读帧失败"或笔记本摄像头
    误认为 C960。
    """
    opens = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, DEFAULT_BACKEND)
        ok_cnt = 0
        if cap.isOpened():
            for _ in range(5):
                ok, frame = cap.read()
                if ok and frame is not None and frame.size > 0:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    if float(gray.mean()) > 1.0:   # 非纯黑
                        ok_cnt += 1
        cap.release()
        if ok_cnt >= min_ok:
            opens.append(i)
    return opens


def save_camera_index(index: int) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"index": int(index)}, f)


def _load_saved_index():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("index")
    except Exception:
        return None


def get_camera_index(preferred=None) -> int:
    """获取摄像头索引，优先级：显式 --index > 配置保存值 > 扫描。

    DirectShow 索引热插拔会漂移。保存索引仍有效则用；否则扫描——但**多设备
    歧义时不得静默选择第一个**（可能选到笔记本摄像头而非 C960），必须显式传
    --index 或用 probe_camera.py 确认。
    """
    if preferred is not None:
        return int(preferred)
    saved = _load_saved_index()
    opens = detect_camera_indices()
    if saved is not None and saved in opens:
        return saved
    if len(opens) == 1:
        save_camera_index(opens[0])
        return opens[0]
    if len(opens) > 1:
        raise SystemExit(
            "检测到多个可用摄像头 {0}，无法确认哪个是 C960。请显式传 index "
            "（当前本机 C960 为索引 1），或先跑 probe_camera.py 确认。".format(opens))
    raise SystemExit("未检测到可用摄像头（DirectShow 索引 0-5 全部读帧失败）")


def imread_unicode(path: str) -> np.ndarray:
    """OpenCV 安全读图（unicode 路径）。"""
    with open(path, "rb") as f:
        data = f.read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Cannot decode image: {path}")
    return img


def imwrite_unicode(path: str, img: np.ndarray) -> bool:
    ok, buf = cv2.imencode(".png", img)
    if ok:
        with open(path, "wb") as f:
            f.write(buf.tobytes())
    return bool(ok)


def open_camera(
    index: int,
    width: int = 1280,
    height: int = 720,
    fps: float = DEFAULT_FPS,
    fourcc: str = DEFAULT_FOURCC,
    backend: int = DEFAULT_BACKEND,
):
    """Open a USB camera in a reproducible DirectShow capture mode."""
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        raise SystemExit(f"cannot open camera index {index}")

    fourcc = fourcc.upper()
    if len(fourcc) != 4:
        cap.release()
        raise SystemExit("fourcc must contain exactly four characters")

    requests = [
        ("fourcc", cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc)),
    ]
    if width and height:
        requests.extend([
            ("width", cv2.CAP_PROP_FRAME_WIDTH, width),
            ("height", cv2.CAP_PROP_FRAME_HEIGHT, height),
        ])
    if fps > 0:
        requests.append(("fps", cv2.CAP_PROP_FPS, fps))

    for label, prop, value in requests:
        if not cap.set(prop, value):
            cap.release()
            raise SystemExit(f"camera rejected requested {label}: {value}")

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = float(cap.get(cv2.CAP_PROP_FPS))
    actual_fourcc_value = int(cap.get(cv2.CAP_PROP_FOURCC))
    actual_fourcc = "".join(
        chr((actual_fourcc_value >> (8 * i)) & 0xFF) for i in range(4)
    )
    if fps > 0 and (actual_fps <= 0 or abs(actual_fps - fps) > 0.5):
        cap.release()
        raise SystemExit(f"requested fps {fps}, got {actual_fps:.2f}")
    if actual_fourcc != fourcc:
        cap.release()
        raise SystemExit(f"requested fourcc {fourcc}, got {actual_fourcc!r}")

    return cap, actual_w, actual_h
