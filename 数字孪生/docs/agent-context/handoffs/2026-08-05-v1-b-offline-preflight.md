# V1-B Task B1 Offline Preflight Handoff

Task/Gate: V1-B Task B1, Offline Ready
Status: ACCEPTED_OFFLINE_ONLY (offline preparation only; not real calibration evidence)

This handoff stops at B1. It does not approve hardware capture, B2, model
fitting, holdout evaluation, `READY`, or `TWIN_USABLE`.

## Changed Files

- `simulation/digital_twin/v1_twin/v1_twin_campaign.py`
  - Adds the minimal V1-B manifest, raw-file SHA-256/size checks, run-ID
    validation, unit and timestamp checks, calibration/holdout ID/hash/time
    isolation, mandatory frozen-profile ID/SHA-256 binding, telemetry interval
    checks, malformed-record rejection, and an offline-only validation report.
  - Synthetic fixtures are reported as `SYNTHETIC_ONLY` and cannot produce a
    readiness verdict.
- `simulation/digital_twin/data/product/acceptance_profiles/v1b_first_campaign_v1.json`
  - Freezes the first campaign profile before capture: PWM command caps
    `260-380` and `480-680`, all three required track segments, sync gates,
    model gates, and threshold basis.
  - This exact profile is explicitly allowlisted and tracked in the B1 Git
    checkpoint; generated simulation data and run products remain ignored.
- `tools/camera_toolchain/v1_b_preflight.py`
  - Adds import, syntax, path, capture `--help`, temporary synthetic-data, and
    temporary output-directory isolation checks only. The default root is the
    formal workspace.
- `simulation/digital_twin/v1_twin/v1_twin_capture.py`
  - Rejects every existing run directory, including an empty one, before any
    raw output can be reused.
- `tools/camera_toolchain/capture_sync_run.py`
  - Uses a subsecond plus random-suffix run ID compatible with the existing
    runtime identifier contract.
- `simulation/digital_twin/tests/test_v1_b_campaign_contract.py`
  - Adds offline contract tests for valid synthetic data, mandatory profile
    binding, missing/duplicate IDs, ID/hash/time overlap, units, timestamps,
    firmware hash, malformed records, raw-file tampering, frozen profiles,
    readiness status variants, and preflight isolation.
- `simulation/digital_twin/tests/test_v1_twin_capture.py`
  - Adds empty-directory overwrite protection, run-ID collision, and unsafe
    run-ID tests.
- `docs/agent-context/handoffs/2026-08-05-v1-b-offline-preflight.md`
  - This handoff.

No STM32 firmware source, control algorithm, communication protocol, safety
stop logic, PCB, UI, MCP, or second-robot file was modified.

## Commands and Results

All commands below were run in
`C:\Users\24668\Desktop\stm32小车\数字孪生`.

- Pre-change baseline recorded before B1 edits:
  `py -3.11 -m pytest -q simulation\digital_twin\tests`
  - Exit code: `0`
  - Result: `603 passed, 5 skipped`.
- TDD regression for the incorrect default preflight root:
  `py -3.11 -m pytest -q simulation\digital_twin\tests\test_v1_b_campaign_contract.py::test_preflight_default_workspace_root_is_the_formal_workspace`
  - Exit code before the path fix: `1` (expected RED).
  - Exit code after the path fix: `0`, `1 passed`.
- TDD regression for a readiness-status variant:
  `py -3.11 -m pytest -q simulation\digital_twin\tests\test_v1_b_campaign_contract.py::test_campaign_readiness_status_variant_is_rejected`
  - Exit code before the status restriction: `1` (expected RED).
  - Exit code after the restriction: `0`, `1 passed`.
- Additional RED-GREEN regressions:
  - `test_missing_acceptance_profile_is_rejected` and
    `test_missing_acceptance_profile_hash_is_rejected`: each exited `1` before
    mandatory profile binding and passed after the fix.
  - `test_telemetry_timestamp_outside_sample_interval_is_rejected` and
    `test_malformed_v1_raw_record_is_reported_as_rejection`: each exited `1`
    before the stream checks and exception boundary, and passed after the fix.
  - `test_preflight_checks_output_directory_isolation_offline`: exited `1`
    before the preflight helper and passed after the helper was added.
- B1 contract and capture tests:
  `py -3.11 -m pytest -q simulation\digital_twin\tests\test_v1_twin_capture.py simulation\digital_twin\tests\test_v1_b_campaign_contract.py`
  - Exit code: `0`
  - Result: `31 passed`.
- Required full test suite:
  `py -3.11 -m pytest -q simulation\digital_twin\tests`
  - Exit code: `0`
  - Result: `628 passed, 5 skipped`.
- Required syntax compilation:
  `py -3.11 -m compileall -q simulation\digital_twin tools`
  - Exit code: `0`.
- Offline preflight help:
  `py -3.11 tools\camera_toolchain\v1_b_preflight.py --help`
  - Exit code: `0`.
  - Result includes `Offline-only V1-B preflight; it does not access hardware or run capture.`
- Offline synthetic preflight:
  `py -3.11 tools\camera_toolchain\v1_b_preflight.py --fake-check`
  - Exit code: `0`.
  - Result: `OFFLINE_PREFLIGHT_PASS`, `hardware_accessed=false`,
    `OFFLINE_CONTRACT_PASS`, `SYNTHETIC_ONLY`.
- Old parent-workspace path scan over active B1 Python sources:
  `Get-ChildItem -Path simulation\digital_twin\v1_twin,tools\camera_toolchain -Recurse -File -Include *.py | Select-String -Pattern 'Desktop\\stm32小车\\simulation|Desktop/stm32小车/simulation' -CaseSensitive`
  - Exit code: `0`.
  - Result: no matches.
- Whitespace check:
  `git diff --check`
  - Exit code: `0`.
  - Result: only Git's existing LF-to-CRLF normalization warnings were shown.
- Workspace/Git status check:
  `git status --short --branch`
  - Exit code: `0`.
  - Result after the B1 checkpoint: branch remains `master` and the working
    tree is clean.
- Acceptance profile tracking check:
  `git check-ignore -q -- simulation/digital_twin/data/product/acceptance_profiles/v1b_first_campaign_v1.json`
  - Before the `.gitignore` fix, exit code: `0`; the profile was ignored by
    `simulation/digital_twin/data/`.
  - After the fix, exit code: `1` and `git ls-files --error-unmatch` resolves
    the profile from the B1 checkpoint.
- Acceptance profile SHA-256:
  `Get-FileHash -Algorithm SHA256 simulation\digital_twin\data\product\acceptance_profiles\v1b_first_campaign_v1.json`
  - Exit code: `0`.
  - SHA-256: `CBB876F048F34E07518A3BF485C7D5D9752BE0737DB600B2A7949C97F4489C9C`.

## VERIFIED

- The current offline suite passes independently with `628 passed, 5 skipped`.
- `compileall` passes for both `simulation/digital_twin` and `tools`.
- A valid synthetic calibration/holdout fixture is accepted only as
  `OFFLINE_CONTRACT_PASS` with evidence level `SYNTHETIC_ONLY` and
  `hardware_accessed=false`.
- The contract rejects missing run IDs, duplicate run IDs, calibration/holdout
  run-ID overlap, raw-file hash overlap, sample-interval overlap, telemetry
  timestamps outside the declared interval, non-monotonic pose timestamps,
  mixed manifest units, mixed raw-stream units, malformed schema records,
  missing or mismatched profile hashes, missing firmware hashes, modified raw
  files, unsafe campaign readiness statuses, and existing capture directories.
- Raw evidence is checked by path containment, file size, and SHA-256 before
  stream parsing. `derived/` paths are rejected as raw evidence.
- The acceptance profile is declared and locked before capture, contains two
  distinct input profiles (`260-380` and `480-680` PWM command caps), and
  requires `STRAIGHT`, `ORDINARY_CURVE`, and
  `TARGET_HIGH_SPEED_ACUTE_CURVE` coverage.
- The profile freezes sync thresholds (`0.95` coverage, `33.3 ms` p95, and
  `MJPG/1280x720/30 fps`) and model thresholds (`10 mm`, `15%`, `15%`, and
  `10%`) without changing them after any capture; actual model gate execution
  remains the B5 responsibility through the existing `V1TwinValidator`.
- The capture output directory is fail-closed for any pre-existing run ID;
  generated IDs use subsecond time and random suffix entropy.
- The preflight default path resolves to the formal workspace, its fake
  campaign and output-directory isolation check run only in temporary
  directories, and it reports `hardware_accessed=false`.
- The workspace remains a Git repository on `master`. Git state was inspected
  but not mutated.

## INFERENCE

- The existing V1 schema and offline validator gates are the current basis for
  the frozen numeric profile thresholds; this is an offline contract mapping,
  not a measurement of this robot's real noise or performance.
- The profile hash is now required by `validate_campaign`; the profile object,
  profile ID, and exact profile SHA-256 must be supplied together. B1 still
  freezes gates rather than evaluating real sync or model metrics.
- The two profile ranges are PWM command-cap intervals. They are not verified
  physical velocity intervals because current V1-A evidence does not verify
  PWM-to-velocity mapping.
- The preflight source and `capture_sync_run.py --help` path contain no
  intentional hardware action in the inspected B1 path; this is static/help
  evidence, not proof of a safe real capture.

## INSUFFICIENT EVIDENCE

- No real camera frame mode, FourCC, FPS, coverage, p95 synchronization, pose,
  telemetry, firmware hash, or physical-speed measurement was collected.
- No real calibration or holdout run IDs, raw-file hashes, or sync reports
  exist. The temporary preflight IDs (`preflight-1` through `preflight-5`) are
  synthetic fixtures only and are not calibration evidence.
- `V1Identification` has not fitted a real model; `V1ModelRegistry` has not
  frozen a real model; no real holdout report has been produced.
- Segment coverage and command-range usage are currently manifest assertions;
  they have not been derived from real raw observations in B1.
- Codex independent acceptance of this B1 handoff is recorded by the
  `ACCEPTED_OFFLINE_ONLY` status above.
- The acceptance profile is versioned in Git; raw campaign data, generated
  reports, and other simulation products remain workspace-local and ignored.

## Hardware Actions

未连接、未烧录、未复位、未发送 START/STOP、未运行小车。

No camera, socket, serial port, ST-Link, debugger, or vehicle-control channel
was opened by this B1 work.

## Data Evidence

- Real run IDs, raw reports, and real raw-file hashes: `none`.
- Synthetic preflight run IDs: `preflight-1` through `preflight-5`, temporary
  only and explicitly `SYNTHETIC_ONLY`.
- Acceptance profile file hash: listed above; it is a profile artifact, not
  raw robot evidence.

## Blocked Next Interface

The next interface is **B2: Hardware Safety Smoke**. It remains blocked pending
a separate explicit hardware authorization. This agent must not execute B2 or
any later hardware Gate.

After this handoff is submitted, work stops here and waits for Codex's
independent review.
