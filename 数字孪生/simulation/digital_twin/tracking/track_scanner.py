#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Scan a closed black line track from a calibrated overhead camera."""

from __future__ import print_function

import argparse
import datetime
import json
import math
import os
import tempfile
import time

import cv2
import numpy as np

try:
    from .config_io import DEFAULT_CONFIG_PATH, load_config, open_camera
except ImportError:  # pragma: no cover - direct script execution
    from config_io import DEFAULT_CONFIG_PATH, load_config, open_camera


DEFAULT_TRACK_MAP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "track_map.json",
)
DEFAULT_PREVIEW_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "track_scan_preview.png",
)


class TrackScanError(RuntimeError):
    """A recoverable track scan failure that can be shown to the user."""


def _validate_floor(floor):
    if not floor.get("calibrated"):
        raise TrackScanError("地面尚未标定，请先运行地面四点标定")
    width_m = float(floor.get("width", 0))
    height_m = float(floor.get("height", 0))
    if not (math.isfinite(width_m) and math.isfinite(height_m)):
        raise TrackScanError("地面尺寸不是有效数字")
    if width_m <= 0.1 or height_m <= 0.1:
        raise TrackScanError("地面尺寸太小，请检查标定配置")
    homography = np.asarray(floor.get("homography"), dtype=np.float64)
    if homography.shape != (3, 3) or not np.isfinite(homography).all():
        raise TrackScanError("地面标定矩阵无效，请重新标定")
    if abs(np.linalg.det(homography)) < 1e-12:
        raise TrackScanError("地面标定矩阵不可逆，请重新标定")
    return width_m, height_m, homography


def _resample_closed(points, count):
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if len(points) < 3:
        raise TrackScanError("轨道边缘点太少")
    closed = np.vstack([points, points[0]])
    segments = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    perimeter = float(segments.sum())
    if perimeter <= 1e-6:
        raise TrackScanError("轨道边缘长度为零")
    distances = np.concatenate([[0.0], np.cumsum(segments)])
    targets = np.linspace(0.0, perimeter, int(count), endpoint=False)
    result = np.empty((len(targets), 2), dtype=np.float64)
    segment_index = 0
    for index, target in enumerate(targets):
        while (
            segment_index + 1 < len(distances) - 1
            and distances[segment_index + 1] <= target
        ):
            segment_index += 1
        length = segments[segment_index]
        fraction = 0.0 if length <= 1e-9 else (
            target - distances[segment_index]
        ) / length
        result[index] = (
            closed[segment_index] * (1.0 - fraction)
            + closed[segment_index + 1] * fraction
        )
    return result


def _signed_area(points):
    shifted = np.roll(points, -1, axis=0)
    return 0.5 * float(
        np.sum(points[:, 0] * shifted[:, 1] - shifted[:, 0] * points[:, 1])
    )


def _align_contours(outer, inner):
    if _signed_area(outer) * _signed_area(inner) < 0:
        inner = inner[::-1].copy()
    best_shift = 0
    best_error = float("inf")
    for shift in range(len(inner)):
        rolled = np.roll(inner, shift, axis=0)
        error = float(np.mean(np.sum((outer - rolled) ** 2, axis=1)))
        if error < best_error:
            best_error = error
            best_shift = shift
    return outer, np.roll(inner, best_shift, axis=0)


def _smooth_closed(points, radius=4):
    smoothed = np.zeros_like(points, dtype=np.float64)
    weights = []
    for offset in range(-radius, radius + 1):
        weight = radius + 1 - abs(offset)
        smoothed += np.roll(points, offset, axis=0) * weight
        weights.append(weight)
    return smoothed / float(sum(weights))


def _track_length(points):
    return float(
        np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum()
    )


def _find_ring_component(binary):
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )
    image_area = float(binary.shape[0] * binary.shape[1])
    candidates = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        area_fraction = area / image_area
        if area_fraction < 0.002 or area_fraction > 0.55:
            continue
        component = np.uint8(labels == label) * 255
        contours, hierarchy = cv2.findContours(
            component,
            cv2.RETR_CCOMP,
            cv2.CHAIN_APPROX_NONE,
        )
        if not contours or hierarchy is None:
            continue
        hierarchy = hierarchy[0]
        outer_indices = [
            index for index, item in enumerate(hierarchy) if item[3] < 0
        ]
        for outer_index in outer_indices:
            child_indices = [
                index
                for index, item in enumerate(hierarchy)
                if item[3] == outer_index
            ]
            if not child_indices:
                continue
            inner_index = max(
                child_indices,
                key=lambda index: abs(cv2.contourArea(contours[index])),
            )
            outer_area = abs(cv2.contourArea(contours[outer_index]))
            inner_area = abs(cv2.contourArea(contours[inner_index]))
            if outer_area <= 1 or inner_area / outer_area < 0.08:
                continue
            candidates.append(
                (
                    area,
                    component,
                    contours[outer_index],
                    contours[inner_index],
                    area_fraction,
                )
            )
    if not candidates:
        raise TrackScanError(
            "没有识别到闭合黑色轨道。请移走小车、减少阴影，并确保整圈轨道都在画面内"
        )
    return max(candidates, key=lambda item: item[0])


def extract_track_map(frame, config, pixels_per_meter=500):
    """Return a metric track map from one calibrated camera frame."""
    if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
        raise TrackScanError("摄像头没有返回有效画面")
    floor = config.get("floor") or {}
    width_m, height_m, homography = _validate_floor(floor)
    ppm = int(pixels_per_meter)
    if ppm < 150 or ppm > 1200:
        raise ValueError("pixels_per_meter must be between 150 and 1200")
    width_px = max(64, int(round(width_m * ppm)))
    height_px = max(64, int(round(height_m * ppm)))
    metric_to_pixels = np.array(
        [[ppm, 0.0, 0.0], [0.0, ppm, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    image_to_topdown = np.matmul(metric_to_pixels, homography)
    topdown = cv2.warpPerspective(
        frame,
        image_to_topdown,
        (width_px, height_px),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )

    gray = cv2.cvtColor(topdown, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    threshold, binary = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, open_kernel)
    margin = max(3, int(round(ppm * 0.008)))
    binary[:margin, :] = 0
    binary[-margin:, :] = 0
    binary[:, :margin] = 0
    binary[:, -margin:] = 0

    area, component, outer_raw, inner_raw, area_fraction = _find_ring_component(
        binary
    )
    sample_count = 320
    outer = _resample_closed(outer_raw[:, 0, :], sample_count)
    inner = _resample_closed(inner_raw[:, 0, :], sample_count)
    outer, inner = _align_contours(outer, inner)
    paired_widths_px = np.linalg.norm(outer - inner, axis=1)
    width_median = float(np.median(paired_widths_px) / ppm)
    width_cv = float(
        np.std(paired_widths_px) / max(np.mean(paired_widths_px), 1e-6)
    )
    if width_median < 0.008 or width_median > min(width_m, height_m) * 0.35:
        raise TrackScanError(
            "识别出的轨道宽度不合理，请改善照明或重新进行地面标定"
        )

    centerline_px = _smooth_closed((outer + inner) * 0.5, radius=4)
    centerline_px = _resample_closed(centerline_px, 180)
    centerline_m = centerline_px / float(ppm)
    length_m = _track_length(centerline_m)
    if length_m < max(0.5, min(width_m, height_m)):
        raise TrackScanError("识别出的轨道过短，请确保整圈轨道都在标定区域内")

    quality = max(
        0.0,
        min(1.0, 1.0 - min(width_cv, 1.0) * 0.55),
    )
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = {
        "version": 1,
        "source": "overhead_camera",
        "created_at": created_at,
        "floor": {
            "width_m": round(width_m, 6),
            "height_m": round(height_m, 6),
            "calibration_revision": int(
                floor.get("calibration_revision", 0)
            ),
        },
        "track": {
            "closed": True,
            "width_m": round(width_median, 6),
            "length_m": round(length_m, 6),
            "points": [
                {"x": round(float(point[0]), 6), "z": round(float(point[1]), 6)}
                for point in centerline_m
            ],
        },
        "detection": {
            "threshold": round(float(threshold), 2),
            "component_pixels": int(area),
            "area_fraction": round(float(area_fraction), 6),
            "width_variation": round(width_cv, 4),
            "quality": round(quality, 3),
        },
    }

    preview = topdown.copy()
    cv2.drawContours(preview, [outer_raw], -1, (70, 210, 255), 2)
    cv2.drawContours(preview, [inner_raw], -1, (70, 210, 255), 2)
    preview_points = np.round(centerline_px).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(preview, [preview_points], True, (40, 70, 255), 3)
    cv2.putText(
        preview,
        "track %.2fm  width %.3fm  quality %.2f"
        % (length_m, width_median, quality),
        (14, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (20, 20, 20),
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        preview,
        "track %.2fm  width %.3fm  quality %.2f"
        % (length_m, width_median, quality),
        (14, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (250, 250, 250),
        1,
        cv2.LINE_AA,
    )
    return result, preview


def save_track_map(path, track_map):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(
        prefix=".track_map_",
        suffix=".json",
        dir=directory,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(track_map, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def load_track_map(path=DEFAULT_TRACK_MAP_PATH):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TrackScanError("已保存的轨道文件格式无效")
    track = payload.get("track") or {}
    if not track.get("closed") or len(track.get("points") or []) < 8:
        raise TrackScanError("已保存的轨道数据不完整")
    return payload


def capture_track_map(
    config_path=DEFAULT_CONFIG_PATH,
    source_override=None,
    output_path=DEFAULT_TRACK_MAP_PATH,
    preview_path=DEFAULT_PREVIEW_PATH,
):
    config = load_config(config_path)
    _validate_floor(config.get("floor") or {})
    capture = open_camera(config["camera"], source_override)
    frames = []
    try:
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and len(frames) < 7:
            ok, frame = capture.read()
            if ok and frame is not None:
                frames.append(frame)
            time.sleep(0.035)
    finally:
        capture.release()
    if len(frames) < 3:
        raise TrackScanError(
            "摄像头读取失败；若位姿跟踪正在使用同一个摄像头，请先关闭跟踪预览后重试"
        )
    median_frame = np.median(np.stack(frames[-5:], axis=0), axis=0).astype(
        np.uint8
    )
    track_map, preview = extract_track_map(median_frame, config)
    save_track_map(output_path, track_map)
    if preview_path:
        cv2.imwrite(preview_path, preview)
    return track_map


def main():
    parser = argparse.ArgumentParser(description="扫描闭合黑色现实轨道")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--source", default=None)
    parser.add_argument("--image", default=None)
    parser.add_argument("--output", default=DEFAULT_TRACK_MAP_PATH)
    parser.add_argument("--preview", default=DEFAULT_PREVIEW_PATH)
    args = parser.parse_args()
    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            raise TrackScanError("无法读取图片：%s" % args.image)
        payload, preview = extract_track_map(frame, load_config(args.config))
        save_track_map(args.output, payload)
        cv2.imwrite(args.preview, preview)
    else:
        payload = capture_track_map(
            config_path=args.config,
            source_override=args.source,
            output_path=args.output,
            preview_path=args.preview,
        )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
