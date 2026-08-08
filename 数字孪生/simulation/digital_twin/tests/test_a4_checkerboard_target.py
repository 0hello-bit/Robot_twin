from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import cv2
import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm


ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = ROOT / "tools" / "camera_toolchain" / "generate_a4_checkerboard.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_a4_checkerboard_under_test", GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generator_emits_a4_metadata_and_outputs(tmp_path):
    generator = _load_generator()
    result = generator.generate_target(tmp_path)

    assert result.pdf_path.exists()
    assert result.png_path.exists()
    assert result.metadata_path.exists()
    metadata = json.loads(result.metadata_path.read_text("utf-8"))
    assert metadata["page_mm"] == [297.0, 210.0]
    assert metadata["square_size_mm"] == 25.0
    assert metadata["active_grid_mm"] == [250.0, 175.0]


def test_generated_preview_contains_9x6_checkerboard(tmp_path):
    generator = _load_generator()
    result = generator.generate_target(tmp_path)

    image = cv2.imread(str(result.png_path), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    found, _ = cv2.findChessboardCorners(image, (9, 6), None)
    assert found


def test_generated_pdf_has_a4_landscape_media_box(tmp_path):
    generator = _load_generator()
    result = generator.generate_target(tmp_path)

    page = PdfReader(str(result.pdf_path)).pages[0]
    assert float(page.mediabox.width) == pytest.approx(297.0 * mm)
    assert float(page.mediabox.height) == pytest.approx(210.0 * mm)
