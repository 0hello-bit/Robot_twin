# DS bounded rework: R3 exploratory profile r2

Date: 2026-08-04
Coordinator verdict on r1: REJECT
Scope: fix the profile/export evidence contract only, then stop for Codex review.

## Preserve boundaries

- Do not modify or add files under
  `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/`.
- Do not wire PoseTracker, route conversion, 4B-4 capture, firmware, or A4 tools.
- Do not use hardware, camera, network, ESP, MCU, flashing, reset, or motor commands.
- Do not perform Git writes or delete/revert unrelated files.
- Reuse the existing implementation; this is a bounded RED -> GREEN correction.

## Blocking defect 1: pixel-domain provenance

Codex reproduced this failure:

```text
source: joint_current_undistortion.json
source optimizer.undistortion: intrinsics file
build_profile result: ACCEPTED
exported input_domain: RAW_PIXEL
```

`export_exploratory_profile.py` must validate both:

- `method` is exactly
  `joint pixel-to-mm homography plus one in-plane angle per training view`;
- `optimizer.undistortion` is exactly `disabled` before assigning `RAW_PIXEL`.

Missing or different values must raise `CalibrationProfileError` before creating
an output directory. Add synthetic tests and one regression using the existing
`joint_current_undistortion.json`; it must be rejected.

## Blocking defect 2: strict profile parsing

The strict contract currently silently accepts and normalizes malformed identity
fields. Codex reproduced acceptance of fractional image dimensions, string
`schema_version`, and an empty camera model.

Make `CalibrationProfile.from_dict()` reject rather than coerce:

- `schema_version` must be an integer and not `bool`;
- `camera.image_size` must contain exactly two positive integers, not `bool`;
- `camera.model`, `calibration_id`, and `pose_absolute_accuracy` must be non-empty
  strings;
- numeric accuracy fields must reject `bool`.

Add focused tests for each rejection. Do not redesign the schema.

## Evidence and wording correction

Create a new evidence directory only:

`.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r2/`

Run the fixed exporter against the pinned corrected raw source and write the two
generated JSON files there. They may remain byte-identical to r1 if the payload
does not change. Write a new `ds_execution_report.md` in r2 that:

1. states that the exporter generated exactly `calibration_profile.json` and
   `verification_report.json`;
2. states that `ds_execution_report.md` is a hand-written DS handback, not an
   exporter output;
3. lists pytest/py_compile cache files as ignored temporary execution artifacts;
4. records r2 source/profile/verification/report hashes and exact test outputs;
5. describes 10.627/11.011 mm as cross-validation estimates for the model class
   used to select the full-fit matrix, not a direct holdout evaluation of that
   exact full-16-view matrix;
6. keeps `RAW_PIXEL`, `EXPLORATORY_RELATIVE_ONLY`, formal 2 mm `REJECT`, runtime
   not wired, and AprilTag height parallax unresolved;
7. states no Git write, hardware, camera, or network operation occurred.

Update the correction block in `docs/agent-context/CURRENT_STATUS.md` to point to
r2 and include the same model-class/direct-matrix distinction. Preserve history.

## Required fresh verification

```powershell
py -3.11 -m pytest -q `
  simulation/digital_twin/tests/test_v1_twin_calibration_profile.py `
  simulation/digital_twin/tests/test_export_exploratory_profile.py `
  simulation/digital_twin/tests/test_v1_twin_calibration.py `
  simulation/digital_twin/tests/test_v1_twin_pose_tracker.py

py -3.11 -m py_compile `
  simulation/digital_twin/v1_twin/v1_twin_calibration_profile.py `
  .embeddedskills/tools/camera_toolchain/export_exploratory_profile.py
```

Also record the real undistorted-source rejection and prove r1 hashes did not
change. Stop after writing the r2 report and wait for Codex acceptance.
