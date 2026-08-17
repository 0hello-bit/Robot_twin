# Sync Trajectory Dashboard Design

## Goal

Provide a local, dependency-free web report for the latest real synchronization
run. The report must make the camera trajectory, MPU6050 heading, fusion
heading, frame-analysis loss, and clock/alignment gates inspectable without
claiming an independent inertial position estimate that the captured telemetry
does not contain.

## Evidence Boundary

The run contains camera `x_mm`/`y_mm`/`yaw_rad` poses and MPU6050
`imu_yaw_rad` samples. It does not contain accelerometer data or wheel odometry
that could support an independent 2D inertial position. `fusion.jsonl` therefore
contains camera-derived position with fused heading, not a second position
track. The UI must show this limitation explicitly and must not plot a
synthetic IMU position.

## Recommended Approach

Create a small Python data-preparation module and a static HTML dashboard. The
module reads one run directory, validates the expected JSONL fields, downsamples
only for rendering when necessary, and emits a compact `dashboard_data.json`.
The HTML uses Canvas and native browser APIs only, so it can be served by the
standard-library HTTP server and does not add a frontend dependency.

The page has four evidence views:

1. A trajectory plot showing camera `x/y` in millimetres, with points colored
   by fusion quality. A separate "fusion position" line is intentionally not
   drawn because its position is camera-derived.
2. A heading plot comparing camera heading, raw MPU6050 heading, and fused
   heading over relative time, plus a numeric p95 heading residual when the
   source records support it.
3. A capture-health strip showing written video frames, processed analysis
   frames, analysis drops, telemetry count, and the camera/telemetry time-span.
4. A gate panel showing alignment and causal-clock verdicts, with the exact
   thresholds and observed values needed to interpret the result.

## Data Flow

`build_sync_dashboard.py` reads `sync_report.json`, `pose.jsonl`,
`telemetry.jsonl`, `fusion.jsonl`, and `frame_index.jsonl`. It normalizes all
timestamps to seconds relative to the first captured timestamp, joins fusion
records to their camera timestamps, and emits explicit availability flags for
position comparison. Missing fields produce an unavailable panel, not a
zero-filled series.

## Visual Direction

The page is a measurement console rather than a marketing dashboard: warm
paper-white surfaces, graphite text, a coral camera trace, cyan IMU trace, and
amber warning states. The signature element is a narrow evidence rail that
keeps the verdict, p95 timing, and "position difference unavailable" boundary
visible beside the plots. Layout is dense on desktop and collapses to a single
column on mobile; canvas plots have text summaries for keyboard and reduced
motion users.

## Failure Handling

The builder exits non-zero with a readable error when the run directory is
missing or required files are malformed. Optional fusion or frame-index data
is represented as unavailable with a visible explanation. The dashboard never
turns `causal_sync=FAIL` into a pass and never labels command telemetry as
independent physical-motion evidence.

## Test Scope

Unit tests cover JSONL parsing, timestamp normalization, field availability,
heading residual calculation, and propagation of the causal-clock verdict.
One fixture represents this real run's schema; a second fixture omits
accelerometer/position fields to prove the UI data layer does not invent an
inertial position.
