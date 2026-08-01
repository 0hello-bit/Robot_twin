"""Task 4B-4 fix: 同步采集辅助（离线可测，无硬件依赖）。

解决的问题（审核事实复核后）：
1. DroidCam 实际可能返回 640x480，而内参与 homography 是 1280x720。
   `cap.set()` 不能当作设置成功证据，必须读取实际尺寸并 fail closed
   （事实 #11）。→ `validate_frame_dimensions`。
2. 原始数据不可覆盖：每次采集写入独立 run_id 目录；目标文件已存在时
   fail closed（任务 C.5）。→ `resolve_run_output_dir`。

模块无 cv2/socket 依赖，可在无摄像头环境用 pytest 离线测试。
"""

from __future__ import annotations

import os
import re
from typing import Sequence


class CaptureConfigError(RuntimeError):
    """采集配置错误（尺寸不符 / 输出路径冲突）。"""


_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_frame_dimensions(
    actual_size: Sequence[int], expected_size: Sequence[int]
) -> None:
    """严格核对相机实际帧尺寸与标定/homography 的 image_size。

    *actual_size*: (width, height)，来自 `cap.get(CAP_PROP_FRAME_WIDTH/HEIGHT)`
        或 `cap.read()` 返回帧的 shape，不得只依赖 `cap.set()` 的返回值。
    *expected_size*: `CameraCalibration.image_size`（(width, height)）。

    不一致立即抛 CaptureConfigError，fail closed。
    """
    actual = (int(actual_size[0]), int(actual_size[1]))
    expected = (int(expected_size[0]), int(expected_size[1]))
    if actual != expected:
        raise CaptureConfigError(
            "camera frame size mismatch: actual {0} vs calibration/homography "
            "expected {1} — refuse to capture with mismatched intrinsics".format(
                actual, expected
            )
        )


def resolve_run_output_dir(
    out_root: str, run_id: str, required_filenames: Sequence[str]
) -> str:
    """解析并创建独立 run_id 输出目录。

    - run_id 必须是安全的目录名（`[A-Za-z0-9_-]+`），否则抛错。
    - 目录 <out_root>/<run_id> 不存在则创建。
    - 目录内任一 *required_filenames* 已存在 → fail closed（不覆盖原始数据）。
    - 返回目录绝对路径。
    """
    if not run_id or not _RUN_ID_RE.match(run_id):
        raise CaptureConfigError("invalid run_id: {0!r}".format(run_id))
    out_dir = os.path.join(out_root, run_id)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    for name in required_filenames:
        target = os.path.join(out_dir, name)
        if os.path.exists(target):
            raise CaptureConfigError(
                "refusing to overwrite existing artifact: {0}".format(target)
            )
    return out_dir
