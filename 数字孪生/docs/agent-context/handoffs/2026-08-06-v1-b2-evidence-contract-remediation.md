# V1-B B2 Evidence Contract Remediation Handoff

Task/Gate: V1-B B2, offline evidence-contract remediation inside canonical `ground_shakedown.py`
Status: COMPLETED_IMPLEMENTATION_ONLY
Gate status: INSUFFICIENT_EVIDENCE
Date: 2026-08-06 Asia/Shanghai

This task did not run hardware. It only repaired offline evidence expression inside the existing canonical `ground_shakedown` / `transport_soak` boundary. It did not create a second TCP client, protocol, parser, ACK registry, heartbeat path, or session lifecycle.

## Changed files

- `tools/shakedown_toolchain/ground_shakedown.py`
  - Added structured socket lifecycle evidence for connect/close.
  - Exposed exactly-once close call count and close timing/result in the public control report.
  - Added canonical connect wrapper `_connect_and_run_ground_session()` so the existing execute path can report real connect call boundaries without creating a parallel transport path.
  - Extended ffprobe evidence extraction to request and structure `codec_tag_string` / `codec_tag` separately from `codec_name`.
  - Kept missing FourCC/tag evidence as `UNKNOWN` / `INSUFFICIENT_EVIDENCE`; did not relabel `codec_name=mjpeg` to `MJPG`.
- `simulation/digital_twin/tests/test_ground_shakedown.py`
  - Added RED/GREEN coverage for socket connect state reporting, exactly-once close evidence publication, and codec-tag structuring.
- `docs/agent-context/handoffs/2026-08-06-v1-b2-evidence-contract-remediation.md`
  - This handoff.

## Commands and results

- `py -3.11 -m pytest -q .\simulation\digital_twin\tests\test_ground_shakedown.py -k "connect_wrapper or applies_all_speed_steps_before_start_and_stops or camera_graceful_shutdown_requires_mjpeg_720p_30fps or camera_validation_keeps_codec_name_and_marks_missing_codec_tag_unknown"`
  - First RED run exit code `1`.
  - Failure reason: import/collection error because `_connect_and_run_ground_session` did not yet exist. This was the expected failing-test phase before implementation.
- Same targeted pytest command after implementation
  - Exit code `0`.
  - Result: `4 passed, 81 deselected in 0.40s`.
- `py -3.11 -m pytest -q .\simulation\digital_twin\tests\test_ground_shakedown.py`
  - Exit code `0`.
  - Result: `85 passed in 10.79s`.
- `py -3.11 -m compileall -q .\tools\shakedown_toolchain .\simulation\digital_twin`
  - Exit code `0`.
- `git -C . status --short`
  - Exit code `0`.
  - Existing dirty paths outside the allowed scope were preserved and not reverted.

## VERIFIED

- The public control result now includes structured socket evidence:
  - `socket.connect.state` can represent at least `NOT_EXECUTED`, `COMPLETED`, and `FAILED`.
  - `socket.close.state` can represent at least `NOT_EXECUTED`, `COMPLETED`, and `FAILED`.
  - `socket.close.call_count` is exposed, so exactly-once close is evidenced by recorded call count rather than inferred from “no exception”.
  - Close timing fields are published from the actual close call boundary, not synthesized afterward.
- The CLI execute path now goes through the canonical transport boundary and records real `transport.connect()` timing and outcome without adding a second session lifecycle.
- The camera validation path now requests and structures ffprobe `codec_tag_string` and `codec_tag` separately from `codec_name`.
- When ffprobe omits codec-tag/FourCC fields, the report keeps:
  - `video.codec_name == "mjpeg"` unchanged,
  - `video.codec_tag_string == "UNKNOWN"`,
  - `video.codec_tag == null`,
  - `codec_tag_evidence.status == "INSUFFICIENT_EVIDENCE"`.
- Existing local regression coverage remained green:
  - full `test_ground_shakedown.py`: `85 passed`;
  - compileall succeeded.

## INFERENCE

- The new connect wrapper should improve future B2 handoff expressiveness for real authorized runs because the execute path now has a canonical place to serialize connect timing/result. This is an inference from the code path and offline tests; no new hardware run was performed in this task.
- The separate codec-tag evidence status should make future camera evidence audits stricter and clearer, because a missing FourCC/tag can remain insufficient without falsifying `codec_name`.

## INSUFFICIENT EVIDENCE

- No hardware run was performed in this task, so there is still no new real B2 evidence package proving:
  - actual ESP socket connect/disconnect timestamps on the hardware run,
  - actual camera codec-tag/FourCC observed from a real authorized camera session,
  - firmware identity, wheel motion, or any B2 PASS condition.
- Offline tests do not upgrade B2 gate state. B2 remains `INSUFFICIENT_EVIDENCE`.
- This remediation does not itself prove that a future real ffprobe invocation will always yield codec-tag/FourCC on the user’s camera stack; it only ensures the canonical report can preserve the real outcome.

## Exact hardware actions

- connected: none
- camera opened: none
- TCP socket to `192.168.110.236`: none
- serial/debugger/Keil/OpenOCD/J-Link: none
- flashed: none
- reset: none
- START/STOP/P/H sent to hardware: none
- motion: none

## Unresolved risks

- The working tree was already dirty outside this task’s allowed files. Those paths were preserved, not audited or modified here.
- The new connect evidence path was verified offline through the helper and report structure, not through a live authorized B2 execution.
- The new codec-tag evidence path depends on ffprobe output shape; if a future live environment returns different field formats, that must be judged from the raw report of that run, not assumed from this offline task.

## Next interface

Parent-agent review only. After parent review, wait for one fresh explicit B2 hardware authorization before any new real hardware execution. Do not declare B2 PASS and do not start another B2/B3 action automatically.

---

## Remediation round 2 (post independent read-only review)

This round addressed the review-rejected gaps without expanding scope beyond the canonical `ground_shakedown` boundary.

### Additional changed behavior

- FourCC/tag is now fail-closed:
  - missing `codec_tag_string` blocks camera success;
  - wrong `codec_tag_string` blocks camera success;
  - if `codec_tag` is present and does not match `0x47504A4D`, camera success is blocked;
  - `codec_name` remains the real ffprobe value (for example `mjpeg`), not rewritten to `MJPG`.
- Socket lifecycle now participates in final verdict:
  - missing socket lifecycle evidence returns `INSUFFICIENT_EVIDENCE`;
  - known connect/close failure or `close.call_count != 1` returns `SHAKEDOWN_FAIL`;
  - PASS requires explicit `connect=COMPLETED`, `close=COMPLETED`, and `close.call_count == 1`.
- `_connect_and_run_ground_session()` now closes once after successful connect when `raw_logger_factory()` or `session_runner()` fails outside canonical `_SessionLoop`, while avoiding a second close when canonical `run_ground_session()` already closed the transport.

### Additional commands and results

- `py -3.11 -m pytest -q .\simulation\digital_twin\tests\test_ground_shakedown.py -k "missing_codec_tag_unknown or wrong_codec_tag or requires_socket_lifecycle or bad_socket_lifecycle or raw_logger_factory_or_session_runner_fail or does_not_double_close_canonical_session_and_reports_close_failure or precedence_failure_then_missing_evidence_then_pass"`
  - First RED run exit code `1`.
  - Result: `10 failed, 1 passed, 83 deselected in 0.67s`.
  - Verified failures matched the review findings: missing/wrong codec tag still PASS, socket lifecycle ignored by verdict, and no close-on-exception after successful connect.
- Same targeted pytest command after remediation
  - Exit code `0`.
  - Result: `11 passed, 83 deselected in 0.21s`.
- `py -3.11 -m pytest -q .\simulation\digital_twin\tests\test_ground_shakedown.py`
  - Exit code `0`.
  - Result: `94 passed in 11.02s`.
- `py -3.11 -m compileall -q .\tools .\simulation\digital_twin`
  - Exit code `0`.

### VERIFIED (round 2)

- Missing codec-tag evidence now fail-closes camera validation:
  - `report["verdict"] == "FAIL"`
  - `report["camera_verdict"] == "FAIL"`
  - `codec_tag_evidence.status == "INSUFFICIENT_EVIDENCE"` for missing tag string.
- Wrong codec-tag evidence now fail-closes camera validation:
  - non-`MJPG` `codec_tag_string` yields `codec_tag_evidence.status == "FAIL"`;
  - mismatched `codec_tag` value yields `codec_tag_evidence.status == "FAIL"`;
  - either case prevents camera PASS.
- Final shakedown PASS now requires valid socket lifecycle evidence in the control report.
- Successful connect followed by `raw_logger_factory()` failure or `session_runner()` failure now causes one close attempt on the existing transport boundary.
- If canonical `run_ground_session()` already supplied a completed close record, the wrapper does not add a second close.

### INFERENCE (round 2)

- Future real B2 reports should be more audit-friendly because camera success and overall success now both depend on concrete socket/FourCC evidence rather than side-channel interpretation.

### INSUFFICIENT EVIDENCE (round 2)

- This remains an offline repair only. No real socket, camera, firmware, or motion evidence was produced in this round.
- The remediation proves contract behavior under tests, not that the next hardware-authorized B2 run will satisfy the tightened evidence gate.

---

## Remediation round 3 (follow-up Important blockers)

This round fixed the remaining wrapper/orchestration evidence gaps without changing the canonical transport/control boundary.

### Additional changed behavior

- `_connect_and_run_ground_session()` no longer retries `transport.close()` when the canonical session already returned a structured close attempt with `close.call_count >= 1`, even if that canonical close failed.
- After successful connect, wrapper-side `raw_logger_factory()` / non-canonical `session_runner()` exceptions now:
  - attempt exactly one close before propagation, including `KeyboardInterrupt` / `SystemExit` class paths via `BaseException`;
  - attach a structured failure/control report to the original exception;
  - preserve close failure state/count/timestamp/error without overwriting the original exception.
- `orchestrate_shakedown()` now consumes the attached structured failure report on the session-exception path so published `shakedown_report.json` retains `control.socket` evidence.

### Additional commands and results

- `py -3.11 -m pytest -q .\simulation\digital_twin\tests\test_ground_shakedown.py -k "retry_canonical_failed_close_attempt or keeps_socket_lifecycle_from_wrapper_exception or keyboard_interrupt_still_closes_and_preserves_original_exception"`
  - First RED run exit code `1`.
  - Result: `3 failed, 94 deselected in 0.49s`.
- Same targeted pytest command after remediation
  - Exit code `0`.
  - Result: `3 passed, 94 deselected in 0.27s`.
- `py -3.11 -m pytest -q .\simulation\digital_twin\tests\test_ground_shakedown.py -k "retry_canonical_failed_close_attempt or keeps_socket_lifecycle_from_wrapper_exception or keyboard_interrupt_still_closes_and_preserves_original_exception or raw_logger_factory_or_session_runner_fail or does_not_double_close_canonical_session_and_reports_close_failure"`
  - Exit code `0`.
  - Result: `5 passed, 92 deselected in 0.39s`.
- `py -3.11 -m pytest -q .\simulation\digital_twin\tests\test_ground_shakedown.py`
  - Exit code `0`.
  - Result: `97 passed in 10.89s`.
- `py -3.11 -m pytest -q .\simulation\digital_twin\tests`
  - Exit code `0`.
  - Result: `645 passed, 5 skipped in 25.93s`.
- `py -3.11 -m compileall -q .\tools .\simulation\digital_twin`
  - Exit code `0`.

### VERIFIED (round 3)

- Canonical `close FAILED + call_count=1` is now treated as an already-attempted close; the wrapper does not issue a second close call.
- Post-connect wrapper exceptions now preserve structured `control.socket` evidence all the way into the final published shakedown failure report.
- `KeyboardInterrupt` on the post-connect path now still triggers one close attempt before the original interrupt is re-raised.
- A close failure during that cleanup path is recorded structurally and does not replace the original exception.

### INFERENCE (round 3)

- Future audits of failed B2 attempts should now be able to distinguish:
  - canonical close failure already returned by `_SessionLoop`,
  - wrapper cleanup close failure after a post-connect exception,
  - and missing lifecycle evidence,
  without requiring inference from transport side effects alone.

### INSUFFICIENT EVIDENCE (round 3)

- This is still offline-only remediation. No hardware session, no real socket endpoint, and no real camera process was exercised against the B2 hardware target in this round.
- Tightened exception-path evidence handling does not upgrade B2 gate state; B2 remains `INSUFFICIENT_EVIDENCE`.

---

## Remediation round 4 (final boundary fix)

This round fixed the last wrapper/canonical close-boundary gaps while staying inside the existing canonical `ground_shakedown` lifecycle.

### Changed files

- `tools\shakedown_toolchain\ground_shakedown.py`
- `simulation\digital_twin\tests\test_ground_shakedown.py`
- `docs\agent-context\handoffs\2026-08-06-v1-b2-evidence-contract-remediation.md`

### Additional changed behavior

- `_connect_and_run_ground_session()` no longer returns a non-dict `session_runner()` result directly after a successful connect.
  - It now closes exactly once first;
  - then raises `TypeError("session_runner must return dict, got <type>")`;
  - and attaches a structured failure report so `orchestrate_shakedown()` can publish auditable `control.socket` evidence.
- Wrapper-side `_close_once_if_needed()` is now `BaseException`-safe for `transport.close()`:
  - `KeyboardInterrupt` / `SystemExit` raised by `close()` are recorded into structured close evidence;
  - they do not replace the original post-connect exception;
  - connect-failure result generation also keeps structured close failure evidence instead of losing it during cleanup.
- Canonical `_SessionLoop._close()` is now `BaseException`-safe:
  - `transport.close()` raising `KeyboardInterrupt` / `SystemExit` is converged into the normal fail-closed close result;
  - raw freeze/report publication can still complete;
  - no second close is introduced.

### Additional commands and results

- `py -3.11 -m pytest -q .\simulation\digital_twin\tests\test_ground_shakedown.py -k "non_dict_session_result_closes_and_attaches_failure_report or close_keyboard_interrupt_does_not_override_original_exception or keeps_socket_lifecycle_for_non_dict_session_result or keyboard_interrupt_close_still_returns_structured_failure_report or retry_canonical_failed_close_attempt or keeps_socket_lifecycle_from_wrapper_exception or keyboard_interrupt_still_closes_and_preserves_original_exception"`
  - First RED run exit code `1`.
  - Result: `1 failed, 2 passed, 94 deselected in 0.77s`.
  - The run also surfaced an unhandled `KeyboardInterrupt: close ctrl-c`, confirming the missing `BaseException` cleanup/report convergence path before remediation.
- Same targeted pytest command after remediation
  - Exit code `0`.
  - Result: `7 passed, 94 deselected in 0.39s`.
- `py -3.11 -m pytest -q .\simulation\digital_twin\tests\test_ground_shakedown.py`
  - Exit code `0`.
  - Result: `101 passed in 11.25s`.
- `py -3.11 -m pytest -q .\simulation\digital_twin\tests`
  - Exit code `0`.
  - Result: `649 passed, 5 skipped in 25.35s`.
- `py -3.11 -m compileall -q .\tools .\simulation\digital_twin`
  - Exit code `0`.

### VERIFIED (round 4)

- A successful connect followed by `session_runner()` returning `None` / `list` / `str` class invalid data no longer leaks an open transport:
  - the wrapper performs exactly one close attempt first;
  - raises a `TypeError`;
  - and attaches `failure_report["control"]["socket"]` with auditable connect/close state.
- If wrapper cleanup `transport.close()` raises `KeyboardInterrupt`, the original post-connect exception still propagates, while close failure is retained structurally as:
  - `socket.close.state == "FAILED"`
  - `socket.close.call_count == 1`
  - `socket.close.failed_monotonic_s != None`
  - `socket.close.error` populated.
- `orchestrate_shakedown()` now publishes the structured `control.socket` evidence for the non-dict wrapper-failure path as part of `shakedown_report.json`.
- Canonical `run_ground_session()` now fail-closes and returns a structured report even when `transport.close()` raises `KeyboardInterrupt`, instead of being interrupted before report convergence/publication.

### INFERENCE (round 4)

- A future hardware-authorized B2 failure caused by wrapper misuse or operator interruption should now leave a more complete offline-auditable socket lifecycle trail in the final report, reducing ambiguity between:
  - invalid session contract,
  - cleanup interruption during close,
  - and canonical close failure.

### INSUFFICIENT EVIDENCE (round 4)

- All evidence in this round is offline test evidence only.
- No real camera, hardware socket, serial link, firmware target, or physical vehicle was accessed.
- These changes do not promote B2 to PASS; B2 remains `INSUFFICIENT_EVIDENCE` until a fresh explicitly authorized hardware rerun produces real evidence.

### Exact hardware actions

- none

### Next interface

Parent-agent re-review only. After that, wait for one new explicit B2 hardware authorization before any real B2 execution. Do not declare B2 PASS.
