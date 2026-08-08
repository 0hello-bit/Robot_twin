# A4 25 mm Checkerboard Target Design

## Purpose

Create a printable planar target for the 1920x1080 camera calibration run. The
target must be large enough in the C960 image while remaining compatible with
the existing OpenCV checkerboard detector and later pixel-to-millimetre
homography fitting.

## Fixed geometry

- Paper: A4 landscape, 297 mm x 210 mm.
- Detector pattern: 9 x 6 inner corners.
- Printed grid: 10 x 7 squares.
- Square size: 25 mm, measured on the printed sheet.
- Active black/white grid: 250 mm x 175 mm.
- White safety border: 10 mm on every side.
- Target footprint: 270 mm x 195 mm, leaving printer-safe margins on A4.

The PDF must be printed at 100 percent scale. The target must be one continuous
grid; it must not be assembled from tiled pages. A rigid, flat backing is
recommended because folds and seams bias corner locations.

## Outputs

- A vector PDF for printing.
- A raster preview for visual inspection only; it is not the print source.
- A small scale reference outside the active grid or a separate measurement
  instruction so the printed 25 mm square size can be checked with a ruler.

## Software compatibility

The new 1080p calibration path must use `square_size_mm=25.0` consistently for
object points, homography control-point coordinates, and geometry preview
tools. The old 15 mm and 1280x720 evidence remains unchanged and is not
rewritten. The square size must be explicit in generated metadata so a future
agent cannot silently mix the two targets.

## Acceptance checks

1. The PDF page is A4 landscape and renders without clipping.
2. The active grid measures 250 mm x 175 mm at 100 percent print scale.
3. The 9 x 6 inner-corner detector succeeds on the rendered preview.
4. The calibration tools compile and their existing tests remain passing.
5. No firmware, camera runtime configuration, old calibration profile, or
   hardware evidence is changed by generating the target.
