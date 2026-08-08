"""Generate the canonical A4 9x6-inner-corner, 25 mm checkerboard target."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.colors import black, white
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import camera_common as cc


PAGE_MM = (297.0, 210.0)  # A4 landscape
WHITE_BORDER_MM = 10.0
PNG_DPI = 300
TARGET_STEM = "a4_checkerboard_9x6_25mm"


@dataclass(frozen=True)
class TargetArtifacts:
    pdf_path: Path
    png_path: Path
    metadata_path: Path


def _target_geometry() -> tuple[float, float, float, float, float, float]:
    cols, rows = cc.CHECKERBOARD_GRID_SQUARES
    square = float(cc.CHECKERBOARD_SQUARE_MM)
    active_w = cols * square
    active_h = rows * square
    target_w = active_w + 2.0 * WHITE_BORDER_MM
    target_h = active_h + 2.0 * WHITE_BORDER_MM
    if target_w > PAGE_MM[0] or target_h > PAGE_MM[1]:
        raise ValueError("checkerboard target does not fit on A4 landscape")
    origin_x = (PAGE_MM[0] - target_w) / 2.0
    origin_y = (PAGE_MM[1] - target_h) / 2.0
    return active_w, active_h, target_w, target_h, origin_x, origin_y


def _draw_pdf(path: Path) -> None:
    active_w, active_h, _target_w, _target_h, origin_x, origin_y = _target_geometry()
    square = float(cc.CHECKERBOARD_SQUARE_MM)
    cols, rows = cc.CHECKERBOARD_GRID_SQUARES
    page_w, page_h = (value * mm for value in PAGE_MM)

    pdf = canvas.Canvas(str(path), pagesize=(page_w, page_h), pageCompression=1)
    pdf.setFillColor(white)
    pdf.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    grid_x = (origin_x + WHITE_BORDER_MM) * mm
    grid_y = (origin_y + WHITE_BORDER_MM) * mm
    pdf.setFillColor(black)
    for row in range(rows):
        for col in range(cols):
            if (row + col) % 2 == 0:
                pdf.rect(
                    grid_x + col * square * mm,
                    grid_y + (rows - row - 1) * square * mm,
                    square * mm,
                    square * mm,
                    fill=1,
                    stroke=0,
                )

    # A short ruler in the top safety border gives a print-scale sanity check.
    ruler_y = (origin_y + WHITE_BORDER_MM + active_h + 5.0) * mm
    ruler_x = (origin_x + WHITE_BORDER_MM) * mm
    pdf.setStrokeColor(black)
    pdf.setLineWidth(0.5)
    pdf.line(ruler_x, ruler_y, ruler_x + square * mm, ruler_y)
    pdf.line(ruler_x, ruler_y - 1.5 * mm, ruler_x, ruler_y + 1.5 * mm)
    pdf.line(ruler_x + square * mm, ruler_y - 1.5 * mm,
             ruler_x + square * mm, ruler_y + 1.5 * mm)
    pdf.showPage()
    pdf.save()


def _draw_png(path: Path) -> tuple[int, int]:
    active_w, active_h, target_w, target_h, origin_x, origin_y = _target_geometry()
    square = float(cc.CHECKERBOARD_SQUARE_MM)
    cols, rows = cc.CHECKERBOARD_GRID_SQUARES
    px_per_mm = PNG_DPI / 25.4
    page_px = tuple(round(value * px_per_mm) for value in PAGE_MM)
    image = Image.new("RGB", page_px, "white")
    draw = ImageDraw.Draw(image)

    grid_x = round((origin_x + WHITE_BORDER_MM) * px_per_mm)
    grid_y = round((origin_y + WHITE_BORDER_MM) * px_per_mm)
    for row in range(rows):
        for col in range(cols):
            if (row + col) % 2 == 0:
                x0 = round((origin_x + WHITE_BORDER_MM + col * square) * px_per_mm)
                y0 = round((origin_y + WHITE_BORDER_MM + row * square) * px_per_mm)
                x1 = round((origin_x + WHITE_BORDER_MM + (col + 1) * square) * px_per_mm)
                y1 = round((origin_y + WHITE_BORDER_MM + (row + 1) * square) * px_per_mm)
                draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill="black")

    ruler_y = round((origin_y + WHITE_BORDER_MM + active_h + 5.0) * px_per_mm)
    ruler_x = grid_x
    ruler_end = round((origin_x + WHITE_BORDER_MM + square) * px_per_mm)
    draw.line((ruler_x, ruler_y, ruler_end, ruler_y), fill="black", width=2)
    draw.line((ruler_x, ruler_y - 6, ruler_x, ruler_y + 6), fill="black", width=2)
    draw.line((ruler_end, ruler_y - 6, ruler_end, ruler_y + 6), fill="black", width=2)

    image.save(path, format="PNG", dpi=(PNG_DPI, PNG_DPI), optimize=False)
    return page_px


def _write_metadata(path: Path, page_px: tuple[int, int]) -> None:
    active_w, active_h, target_w, target_h, origin_x, origin_y = _target_geometry()
    metadata = {
        "schema_version": 1,
        "target_id": TARGET_STEM,
        "page_mm": list(PAGE_MM),
        "orientation": "landscape",
        "pattern_inner_corners": list(cc.CHECKERBOARD_PATTERN),
        "grid_squares": list(cc.CHECKERBOARD_GRID_SQUARES),
        "square_size_mm": float(cc.CHECKERBOARD_SQUARE_MM),
        "active_grid_mm": [active_w, active_h],
        "white_border_mm": WHITE_BORDER_MM,
        "target_footprint_mm": [target_w, target_h],
        "origin_mm": [origin_x, origin_y],
        "print_scale": 1.0,
        "png_dpi": PNG_DPI,
        "png_size_px": list(page_px),
        "scale_reference_mm": float(cc.CHECKERBOARD_SQUARE_MM),
    }
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def generate_target(out_dir: str | Path) -> TargetArtifacts:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pdf_path = out / f"{TARGET_STEM}.pdf"
    png_path = out / f"{TARGET_STEM}.png"
    metadata_path = out / f"{TARGET_STEM}.json"
    _draw_pdf(pdf_path)
    page_px = _draw_png(png_path)
    _write_metadata(metadata_path, page_px)
    return TargetArtifacts(pdf_path, png_path, metadata_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=HERE / "calibration_targets",
        help="directory for the PDF, PNG preview, and metadata JSON",
    )
    args = parser.parse_args()
    artifacts = generate_target(args.out_dir)
    print(f"pdf: {artifacts.pdf_path}")
    print(f"png: {artifacts.png_path}")
    print(f"metadata: {artifacts.metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
