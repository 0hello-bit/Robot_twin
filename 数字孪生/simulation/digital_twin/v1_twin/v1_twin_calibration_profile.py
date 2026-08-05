"""不可变的 calibration profile 契约（R3 raw-pixel exploratory）。

定义地面映射的身份字段，防止 exploratory 结果被误当 2 mm 正式证据：

- calibration_id 唯一标识该映射；
- input_domain=RAW_PIXEL：消费者不得再次去畸变后套用该矩阵；
- quality=EXPLORATORY_RELATIVE_ONLY 或 HOLDOUT_VERIFIED_2MM；
- require_ground_holdout_verified_2mm() 只接受 HOLDOUT_VERIFIED_2MM 且
  stratified_holdout_p95_mm <= 2.0 mm。

设计见
docs/superpowers/specs/2026-08-04-a4-global-charuco-2mm-calibration-design.md §6。
本模块不接入 PoseTracker / TrackMap / 4B-4 capture，不含运行时映射逻辑。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Dict, Tuple

import numpy as np

from v1_twin.v1_twin_calibration import HomographyTransform

SCHEMA_VERSION = 1
FORMAL_2MM_P95_MM = 2.0

_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class CalibrationProfileError(ValueError):
    """Profile 结构、数值或门不满足契约时抛出。"""


class PixelDomain(str, Enum):
    RAW_PIXEL = "RAW_PIXEL"
    UNDISTORTED_PIXEL = "UNDISTORTED_PIXEL"


class CalibrationQuality(str, Enum):
    EXPLORATORY_RELATIVE_ONLY = "EXPLORATORY_RELATIVE_ONLY"
    HOLDOUT_VERIFIED_2MM = "HOLDOUT_VERIFIED_2MM"


@dataclass(frozen=True)
class GroundAccuracyEvidence:
    """地面控制点精度证据（mm）。

    只描述地面控制点；车体绝对位姿精度由 pose_absolute_accuracy 另行声明。
    """

    scope: str
    stratified_holdout_p95_mm: float
    stratified_holdout_max_mm: float
    loo_p95_mm: float
    loo_max_mm: float
    evidence_class: str

    def __post_init__(self) -> None:
        if self.scope != "GROUND_CONTROL_POINTS_ONLY":
            raise CalibrationProfileError(
                "scope must be GROUND_CONTROL_POINTS_ONLY"
            )
        for name in (
            "stratified_holdout_p95_mm",
            "stratified_holdout_max_mm",
            "loo_p95_mm",
            "loo_max_mm",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CalibrationProfileError(
                    f"{name} must be a number and not bool, "
                    f"got {type(value).__name__}"
                )
            if not np.isfinite(value):
                raise CalibrationProfileError(
                    f"{name} must be a finite number"
                )
            if value < 0.0:
                raise CalibrationProfileError(f"{name} must be non-negative")
        if not isinstance(self.evidence_class, str) or not self.evidence_class:
            raise CalibrationProfileError("evidence_class must be non-empty")


@dataclass(frozen=True)
class Provenance:
    """来源证明：工作区相对路径 + 源文件 SHA-256。"""

    source: str
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.sha256, str) or not _SHA256_HEX_RE.fullmatch(
            self.sha256
        ):
            raise CalibrationProfileError("sha256 must be a 64-char hex string")
        if not isinstance(self.source, str) or not self.source:
            raise CalibrationProfileError("source must be a non-empty string")
        if "\\" in self.source:
            raise CalibrationProfileError(
                "source path must use '/' separators"
            )
        if os.path.isabs(self.source):
            raise CalibrationProfileError(
                "source path must be workspace-relative"
            )
        if ".." in PurePosixPath(self.source).parts:
            raise CalibrationProfileError(
                "source path must not contain '..'"
            )


@dataclass(frozen=True)
class CalibrationProfile:
    """不可变标定 profile。映射身份字段强制一致。"""

    schema_version: int
    calibration_id: str
    camera_model: str
    image_size: Tuple[int, int]
    pixel_domain: PixelDomain
    quality: CalibrationQuality
    ground_transform: HomographyTransform
    accuracy: GroundAccuracyEvidence
    pose_absolute_accuracy: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(
            self.schema_version, int
        ):
            raise CalibrationProfileError(
                "schema_version must be an integer and not bool"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise CalibrationProfileError(
                f"unsupported schema_version {self.schema_version}"
            )
        if not isinstance(self.camera_model, str) or not self.camera_model:
            raise CalibrationProfileError(
                "camera_model must be a non-empty string"
            )
        if not isinstance(self.calibration_id, str) or not self.calibration_id:
            raise CalibrationProfileError(
                "calibration_id must be a non-empty string"
            )
        if not isinstance(self.image_size, tuple) or len(self.image_size) != 2:
            raise CalibrationProfileError("image_size must be (width, height)")
        w, h = self.image_size
        if isinstance(w, bool) or isinstance(h, bool):
            raise CalibrationProfileError(
                "image_size must be integers, not bool"
            )
        if (not isinstance(w, int) or not isinstance(h, int)) or w <= 0 or h <= 0:
            raise CalibrationProfileError(
                "image_size must be positive integers"
            )
        if not np.isfinite(self.ground_transform.matrix).all():
            raise CalibrationProfileError("homography must be finite")
        if abs(np.linalg.det(self.ground_transform.matrix)) <= 1e-12:
            raise CalibrationProfileError("homography must be non-singular")
        if (
            not isinstance(self.pose_absolute_accuracy, str)
            or not self.pose_absolute_accuracy
        ):
            raise CalibrationProfileError(
                "pose_absolute_accuracy must be a non-empty string"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationProfile":
        # 严格解析：拒绝而非强制转换。身份字段原样传入，
        # 由 __post_init__ 校验类型与取值；bool 是 int 子类，需单独排除。
        try:
            camera = data["camera"]
            raw_image_size = camera["image_size"]
            if not isinstance(raw_image_size, (list, tuple)) or len(
                raw_image_size
            ) != 2:
                raise ValueError(
                    "camera.image_size must contain exactly two elements"
                )
            image_size = (raw_image_size[0], raw_image_size[1])
            schema_version = data["schema_version"]
            calibration_id = data["calibration_id"]
            camera_model = camera["model"]
            pose_absolute_accuracy = data["pose_absolute_accuracy"]

            gt_data = data["ground_transform"]
            if gt_data.get("type") != "HomographyTransform":
                raise ValueError(
                    "ground_transform.type must be HomographyTransform"
                )
            obj = cls(
                schema_version=schema_version,
                calibration_id=calibration_id,
                camera_model=camera_model,
                image_size=image_size,
                pixel_domain=PixelDomain(data["input_domain"]),
                quality=CalibrationQuality(data["quality"]),
                ground_transform=HomographyTransform.from_dict(gt_data),
                accuracy=GroundAccuracyEvidence(**data["accuracy_evidence"]),
                pose_absolute_accuracy=pose_absolute_accuracy,
                provenance=Provenance(**data["provenance"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CalibrationProfileError(str(exc)) from exc
        # 防伪造：声称 HOLDOUT_VERIFIED_2MM 时 p95 必须 <= 2.0 mm。
        if (
            obj.quality is CalibrationQuality.HOLDOUT_VERIFIED_2MM
            and obj.accuracy.stratified_holdout_p95_mm > FORMAL_2MM_P95_MM
        ):
            raise CalibrationProfileError("formal ground p95 exceeds 2.0 mm")
        return obj

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "calibration_id": self.calibration_id,
            "camera": {
                "model": self.camera_model,
                "image_size": list(self.image_size),
            },
            "input_domain": self.pixel_domain.value,
            "quality": self.quality.value,
            "ground_transform": self.ground_transform.to_dict(),
            "accuracy_evidence": {
                "scope": self.accuracy.scope,
                "stratified_holdout_p95_mm": self.accuracy.stratified_holdout_p95_mm,
                "stratified_holdout_max_mm": self.accuracy.stratified_holdout_max_mm,
                "loo_p95_mm": self.accuracy.loo_p95_mm,
                "loo_max_mm": self.accuracy.loo_max_mm,
                "evidence_class": self.accuracy.evidence_class,
            },
            "pose_absolute_accuracy": self.pose_absolute_accuracy,
            "provenance": {
                "source": self.provenance.source,
                "sha256": self.provenance.sha256,
            },
        }

    def require_ground_holdout_verified_2mm(self) -> None:
        """正式 ground 门：只接受 HOLDOUT_VERIFIED_2MM 且 p95 <= 2.0 mm。"""
        if self.quality is not CalibrationQuality.HOLDOUT_VERIFIED_2MM:
            raise CalibrationProfileError(
                "formal ground use requires HOLDOUT_VERIFIED_2MM"
            )
        if self.accuracy.stratified_holdout_p95_mm > FORMAL_2MM_P95_MM:
            raise CalibrationProfileError("formal ground p95 exceeds 2.0 mm")
