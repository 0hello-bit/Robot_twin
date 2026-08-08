# B3 Offline Observation Gate Handoff

Date: 2026-08-08 Asia/Shanghai
Status: `OFFLINE_VERIFIED_B3_OBSERVATION_GATE_FAILED`

## Scope

This task added a read-only replay gate for retained synchronized capture
artifacts. It evaluates camera observation continuity after the existing sync
gate. It does not run AprilTag detection, change detector parameters, change
calibration, rebuild or flash firmware, or access hardware.

## Reused path

- Input: the existing `frame_index.jsonl` and `sync_report.json` artifacts.
- Existing capture lifecycle, parser, session storage, and sync thresholds
  remain unchanged.
- Derived output:
  `docs/evidence/v1_b3_observation_gate_20260808/report.json`.
- The raw session remains at
  `simulation/digital_twin/logs/c260807144501519/`.

## Declared screening profile

- Expected camera rate: 30 fps.
- Minimum detected-pose ratio: 0.95.
- Maximum gap between detected poses: 2 frame periods.
- Detector p95 processing time: at most one frame period.

These are fixed engineering screening thresholds for this gate. They are not
claims that the physical camera or digital twin is accurate.

## Command and result

```text
py -3.11 tools/camera_toolchain/analyze_b3_observation.py --session-dir simulation/digital_twin/logs/c260807144501519 --output docs/evidence/v1_b3_observation_gate_20260808/report.json --source REAL_SYNC
```

The derived report is reproducible from these input SHA-256 values:

- `frame_index.jsonl`: `f1017a822ed973d01eaed2195f3fae67831d2a571ebdda6046996e22df971cd5`
- `sync_report.json`: `fee2f80747fdaed108eb88e90ccc1fe63ce9806b9734f48465a8b3a64ea217e4`

The replay requires both the sync sub-gate and the overall capture verdict;
both are `PASS` for this run.

## VERIFIED

- The source run declared and passed the existing B3 sync gate.
- The raw run contains 193 readable camera frames and 21 detected poses.
- Detection ratio is `10.8808%`.
- The longest detected-pose gap is `2.75 s`, or `82.5` 30-fps frame periods.
- Detector processing p95 is `70.36154 ms`, above the `33.333333 ms` frame
  budget.
- The report confirms `capture_verdict=PASS`, `sync_gate_verdict=PASS`, and
  zero missing detector-timing fields on readable frames.
- All 172 failed frames are classified in the retained index as
  `candidates_rejected`.
- The observation gate verdict is `FAIL` with evidence status `VERIFIED`.
- The independent PowerShell count and gap calculation match the derived
  report.
- Focused gate and CLI tests pass: `18 passed`.
- Full Python regression passes: `727 passed, 5 skipped`; compileall exits `0`.

## INFERENCE

- Processing time and candidate rejection are plausible contributors to the
  sparse stream, but this gate does not establish the root cause.
- The observation stream is not ready to support a continuous trajectory
  dataset or downstream B3 calibration/holdout use.

## INSUFFICIENT EVIDENCE

- The run predates bounded failed-frame thumbnail retention, so visibility,
  blur, occlusion, contrast, and detector rejection cannot be separated from
  the existing structured record alone.
- The CLI accepts `REAL_SYNC` only for the existing canonical capture roots.
  This prevents accidental labeling of arbitrary temporary data, but the
  analyzer still relies on the canonical capture provenance and cannot prove
  physical origin from files alone.
- No detector, camera-resolution, calibration, firmware, or control change
  has been validated.
- This offline replay does not establish digital-twin accuracy, line-loss
  improvement, speed improvement, or a real A/B comparison.

## Next interface

Do not promote B3 or enter the high-speed candidate loop. After explicit user
authorization, run one bounded synchronized capture through the existing
`capture_sync_run.py` path with the full tag visible from the first frame.
Inspect `frame_index.jsonl`, `failure_frame_summary.json`, and `failed_frames/`.
Only then choose one constrained detector, camera setup, or calibration
experiment.
