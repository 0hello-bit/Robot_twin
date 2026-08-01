"""Cross-language regression tests against the real firmware C protocol module.

The trace runner is compiled from source for this pytest session and receives
hex-encoded bytes.  That keeps malformed bytes (including NUL) distinct from
Python text handling while exercising the production C state machine.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import random
import shutil
import subprocess
from typing import Iterable

import pytest

from real_world.runtime_protocol import (
    ParameterAck,
    ParameterCommand,
    ProtocolError,
    RunCommand,
    RuntimeParameterBoundary,
    frame,
    parse_ack,
    parse_command,
)


ROOT = Path(__file__).resolve().parents[3]
FIRMWARE_DIR = ROOT / "程序" / "3. 麦轮巡线小车" / "User"
PROTOCOL_SOURCE = FIRMWARE_DIR / "twin_control_protocol.c"
RUNNER_SOURCE = Path(__file__).with_name("twin_control_trace_runner.c")
BUILD_DIR = ROOT / ".embeddedskills" / "build"
RUNNER_EXE = BUILD_DIR / "twin_control_trace_runner.exe"
RUNNER_RESPONSE = BUILD_DIR / "twin_control_trace_runner.rsp"
VCVARS_CANDIDATES = (
    Path(os.environ["VCVARS64_BAT"]) if "VCVARS64_BAT" in os.environ else None,
    Path(os.environ["VSINSTALLDIR"]) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if "VSINSTALLDIR" in os.environ else None,
    Path(r"D:\vs2022\VC\Auxiliary\Build\vcvars64.bat"),
)

BASELINE = ParameterCommand("baseline", 1, 35.0, 0.0, 10.0, 680)
CORPUS_SEED = 0x5AFE2026
CORPUS_DIGEST_SHA256 = None  # Will be set to the actual hex digest on first run

# Valid reference frame used for creating malformed variants
_VALID_P = ParameterCommand("camp-001", 2, 40.0, 0.0, 10.0, 680).encode()
_VALID_P_BYTES = _VALID_P.encode("ascii")


@dataclass(frozen=True)
class Observation:
    operation: str
    has_ack: bool
    applied: bool
    motion_inhibited: bool
    result_version: int
    result_campaign_id: str
    result_reason: str
    kp: float
    ki: float
    kd: float
    speed_max: int
    active_version: int
    active_campaign_id: str
    ack_hex: str

    @property
    def ack(self) -> ParameterAck | None:
        if not self.ack_hex:
            return None
        return parse_ack(bytes.fromhex(self.ack_hex).decode("ascii"))


@dataclass(frozen=True)
class RawCase:
    name: str
    payload: bytes


def _msvc_environment() -> dict[str, str] | None:
    """Return an MSVC environment when vcvars can be parsed, otherwise None."""
    if shutil.which("cl.exe") or shutil.which("cl"):
        return os.environ.copy()

    for vcvars in VCVARS_CANDIDATES:
        if vcvars is None or not vcvars.is_file():
            continue
        command = "call {0} >nul && set".format(subprocess.list2cmdline([str(vcvars)]))
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", command],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            check=False,
        )
        environment = os.environ.copy()
        for line in completed.stdout.splitlines():
            if "=" in line:
                name, value = line.split("=", 1)
                if name.upper() == "PATH":
                    environment["PATH"] = value
                else:
                    environment[name] = value
        if shutil.which("cl.exe", path=environment.get("PATH")):
            return environment
    return None


def _run_msvc_compile(response_file: Path) -> subprocess.CompletedProcess[str]:
    """Build from a response file, keeping non-ASCII paths out of cmd.exe parsing."""
    environment = _msvc_environment()
    compiler = shutil.which("cl.exe", path=environment.get("PATH")) if environment else None
    if compiler is not None:
        return subprocess.run(
            [compiler, "@" + str(response_file)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            check=False,
        )

    for vcvars in VCVARS_CANDIDATES:
        if vcvars is not None and vcvars.is_file():
            command = "call {0} >nul && cl @{1}".format(
                subprocess.list2cmdline([str(vcvars)]),
                subprocess.list2cmdline([str(response_file)]),
            )
            return subprocess.run(
                ["cmd.exe", "/d", "/c", command],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="mbcs",
                errors="replace",
                check=False,
            )
    pytest.fail("MSVC cl.exe or a usable vcvars64.bat is required for cross-language tests")


@pytest.fixture(scope="session")
def trace_runner() -> Path:
    """Compile the runner afresh from its C source and the production module."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for artifact in (
        RUNNER_EXE,
        BUILD_DIR / "twin_control_trace_runner.obj",
        BUILD_DIR / "twin_control_protocol.obj",
    ):
        artifact.unlink(missing_ok=True)

    RUNNER_RESPONSE.write_text(
        "\n".join(
            [
                "/nologo",
                "/TC",
                "/W4",
                "/D_CRT_SECURE_NO_WARNINGS",
                '/I"{0}"'.format(FIRMWARE_DIR),
                '"{0}"'.format(RUNNER_SOURCE),
                '"{0}"'.format(PROTOCOL_SOURCE),
                '/Fe"{0}"'.format(RUNNER_EXE),
            ]
        ),
        encoding="mbcs",
    )
    completed = _run_msvc_compile(RUNNER_RESPONSE)
    assert completed.returncode == 0, (
        "trace runner build failed:\nSTDOUT:\n{0}\nSTDERR:\n{1}".format(
            completed.stdout, completed.stderr
        )
    )
    assert RUNNER_EXE.is_file()
    return RUNNER_EXE


def _parse_observation(line: str) -> Observation:
    fields = line.rstrip("\r\n").split(",")
    assert len(fields) == 15 and fields[0] == "O", "unexpected runner output: {0!r}".format(line)
    return Observation(
        operation=fields[1],
        has_ack=fields[2] == "1",
        applied=fields[3] == "1",
        motion_inhibited=fields[4] == "1",
        result_version=int(fields[5]),
        result_campaign_id=fields[6],
        result_reason=fields[7],
        kp=float(fields[8]),
        ki=float(fields[9]),
        kd=float(fields[10]),
        speed_max=int(fields[11]),
        active_version=int(fields[12]),
        active_campaign_id=fields[13],
        ack_hex=fields[14],
    )


def _run_trace(runner: Path, commands: Iterable[str]) -> list[Observation]:
    command_list = list(commands)
    completed = subprocess.run(
        [str(runner)],
        input="".join(command + "\n" for command in command_list),
        capture_output=True,
        text=True,
        encoding="ascii",
        errors="strict",
        check=False,
    )
    assert completed.returncode == 0, (
        "trace runner failed with {0}:\nSTDOUT:\n{1}\nSTDERR:\n{2}".format(
            completed.returncode, completed.stdout, completed.stderr
        )
    )
    lines = [line for line in completed.stdout.splitlines() if line]
    assert len(lines) == len(command_list), (
        "runner emitted {0} records for {1} commands:\n{2}".format(
            len(lines), len(command_list), completed.stdout
        )
    )
    return [_parse_observation(line) for line in lines]


def _hex(payload: bytes | str) -> str:
    if isinstance(payload, str):
        payload = payload.encode("ascii")
    return payload.hex().upper()


def _assert_active(observation: Observation, expected: ParameterCommand) -> None:
    assert observation.kp == pytest.approx(expected.kp)
    assert observation.ki == pytest.approx(expected.ki)
    assert observation.kd == pytest.approx(expected.kd)
    assert observation.speed_max == expected.speed_max
    assert observation.active_version == expected.version
    assert observation.active_campaign_id == expected.campaign_id


def _assert_no_applied_and_baseline(observation: Observation) -> None:
    assert not observation.applied
    assert observation.ack is None or observation.ack.outcome != "APPLIED"
    _assert_active(observation, BASELINE)


def _invalid_corpus() -> list[RawCase]:
    """Create a deterministic, explicitly-labelled corpus of malformed wire bytes."""
    rng = random.Random(CORPUS_SEED)
    cases: list[RawCase] = [
        RawCase("empty-input", b""),
        RawCase("bare-newline", b"\n"),
    ]

    for index in range(8):
        cut = rng.randrange(1, len(_VALID_P_BYTES))
        cases.append(RawCase("truncated-{0:02d}-{1}".format(index, cut), _VALID_P_BYTES[:cut]))

    nul_offset = rng.randrange(1, len(_VALID_P_BYTES) - 1)
    cases.append(RawCase("embedded-nul", _VALID_P_BYTES[:nul_offset] + b"\x00" + _VALID_P_BYTES[nul_offset:]))
    non_ascii_offset = rng.randrange(1, len(_VALID_P_BYTES) - 1)
    cases.append(RawCase("non-ascii-80", _VALID_P_BYTES[:non_ascii_offset] + b"\x80" + _VALID_P_BYTES[non_ascii_offset:]))

    cases.extend(
        [
            RawCase("empty-campaign", frame("P,,2,40,0,10,680").encode("ascii")),
            RawCase("empty-version", frame("P,camp-001,,40,0,10,680").encode("ascii")),
            RawCase("extra-field", frame("P,camp-001,2,40,0,10,680,extra").encode("ascii")),
            RawCase("wrong-checksum", _VALID_P_BYTES[:-3] + b"00\n"),
            RawCase("bare-cr", _VALID_P_BYTES[:-1] + b"\r"),
            RawCase("crlf", _VALID_P_BYTES[:-1] + b"\r\n"),
            RawCase("overlong", b"X" * 97 + b"\n"),
            RawCase("nan", frame("P,camp-001,2,NaN,0,10,680").encode("ascii")),
            RawCase("inf", frame("P,camp-001,2,Inf,0,10,680").encode("ascii")),
            RawCase("version-overflow", frame("P,camp-001,4294967296,40,0,10,680").encode("ascii")),
            RawCase("invalid-start", frame("R,camp-001,run-001,RESUME").encode("ascii")),
            RawCase("two-invalid-frames", _VALID_P_BYTES[:-3] + b"00\n" + frame("R,camp-001,run-001,RESUME").encode("ascii")),
            # Strong NUL killer: complete valid P frame with NUL inserted before LF
            RawCase("nul-before-lf", _VALID_P_BYTES.rstrip(b"\n")[:-1] + b"\x00\n"),
            # Additional edge cases
            RawCase("lowercase-checksum", _VALID_P_BYTES[:-4] + b"00\n"),
            RawCase("bad-checksum-length", _VALID_P_BYTES[:-4] + b"FFF\n"),
            RawCase("negative-kp", frame("P,camp-001,2,-1,0,10,680").encode("ascii")),
            RawCase("negative-speed", frame("P,camp-001,2,35,0,10,-1").encode("ascii")),
            RawCase("exact-96-bytes", b"P," + b"a" * 82 + b",1,2,3,4,5,00\n"),
            RawCase("empty-run-campaign", frame("R,,run-001,STOP").encode("ascii")),
            RawCase("empty-run-id", frame("R,camp-001,,STOP").encode("ascii")),
            RawCase("non-decimal-version", frame("P,camp-001,0x02,35,0,10,680").encode("ascii")),
        ]
    )

    for index in range(8):
        length = rng.randrange(1, 40)
        payload = bytes(rng.randrange(0x20, 0x7F) for _ in range(length)) + b"\n"
        cases.append(RawCase("random-ascii-{0:02d}".format(index), payload))
    return cases


def test_python_encoded_parameter_applies_and_its_c_ack_round_trips(trace_runner: Path):
    """Python's canonical P frame drives the production C safe point unchanged."""
    candidate = ParameterCommand("camp-001", 2, 40.0, 0.0, 10.0, 680)
    boundary = RuntimeParameterBoundary(BASELINE)
    assert parse_command(candidate.encode()) == candidate
    assert boundary.receive(candidate) is None
    expected_ack = boundary.apply_pending()

    observations = _run_trace(trace_runner, ["I", "X " + _hex(candidate.encode()), "A", "Q"])
    received, applied, snapshot = observations[1:]
    assert received.ack is None
    _assert_active(received, BASELINE)
    assert applied.ack == expected_ack
    assert applied.applied
    # Task 2B: firmware starts with motion inhibited by default.
    # Only a valid R,...,START command clears it; applying a P alone does not.
    assert applied.motion_inhibited
    _assert_active(snapshot, candidate)


@pytest.mark.parametrize(
    ("body", "python_reason", "c_reason"),
    [
        ("P,camp-001,2,19,0,10,680", "kp", "PARAM_BOUNDS"),
        ("P,camp-001,2,41,0,10,680", "kp", "STEP_LIMIT"),
        ("P,camp-001,2,40,0,10,+680", "speed_max", "PARAM_BOUNDS"),
        ("P,camp-001,+2,40,0,10,680", "version", ""),
        ("P,camp-001,02,40,0,10,680", "version", ""),
    ],
)
def test_parameter_rejection_agrees_with_python_acceptance_boundary(
    trace_runner: Path, body: str, python_reason: str, c_reason: str
):
    """Both implementations reject malformed/unsafe P input without an active change."""
    packet = frame(body)
    try:
        candidate = parse_command(packet)
    except ProtocolError as error:
        assert python_reason in str(error)
        assert c_reason in ("", "PARAM_BOUNDS")
    else:
        expected = RuntimeParameterBoundary(BASELINE).receive(candidate)
        assert expected is not None and expected.outcome == "REJECTED"
        assert expected.reason == python_reason
        assert c_reason in ("PARAM_BOUNDS", "STEP_LIMIT")

    observations = _run_trace(trace_runner, ["I", "X " + _hex(packet), "A", "Q"])
    received, safe_point, snapshot = observations[1:]
    _assert_no_applied_and_baseline(received)
    _assert_no_applied_and_baseline(safe_point)
    _assert_no_applied_and_baseline(snapshot)
    if c_reason:
        assert received.ack == ParameterAck("camp-001", 2, "REJECTED", c_reason)
    else:
        assert received.ack is None


def test_exponent_form_is_accepted_by_both_parsers_and_applies_at_safe_point(trace_runner: Path):
    """Exponent notation is numeric syntax, not a malformed frame, in both implementations."""
    packet = frame("P,camp-001,2,3.5e1,0,1e1,680")
    candidate = parse_command(packet)
    assert candidate == ParameterCommand("camp-001", 2, 35.0, 0.0, 10.0, 680)
    boundary = RuntimeParameterBoundary(BASELINE)
    assert boundary.receive(candidate) is None
    expected_ack = boundary.apply_pending()

    observations = _run_trace(trace_runner, ["I", "X " + _hex(packet), "A"])
    assert observations[1].ack is None
    assert observations[2].ack == expected_ack
    _assert_active(observations[2], candidate)


def test_concatenated_and_segmented_frames_preserve_real_c_pending_semantics(trace_runner: Path):
    """Byte segmentation and back-to-back frames cannot skip pending/safe-point rules."""
    first = ParameterCommand("camp-001", 2, 40.0, 0.0, 10.0, 680)
    second = ParameterCommand("camp-001", 3, 35.0, 0.0, 10.0, 680)
    split = len(first.encode()) // 2
    segmented = first.encode().encode("ascii")

    segmented_observations = _run_trace(
        trace_runner,
        ["I", "X " + _hex(segmented[:split]), "Q", "X " + _hex(segmented[split:]), "A"],
    )
    assert segmented_observations[1].ack is None
    _assert_active(segmented_observations[2], BASELINE)
    assert segmented_observations[3].ack is None
    assert segmented_observations[4].ack == ParameterAck("camp-001", 2, "APPLIED", "APPLIED")
    _assert_active(segmented_observations[4], first)

    boundary = RuntimeParameterBoundary(BASELINE)
    assert boundary.receive(first) is None
    expected_pending = boundary.receive(second)
    expected_applied = boundary.apply_pending()
    concatenated_observations = _run_trace(
        trace_runner,
        ["I", "X " + _hex(first.encode() + second.encode()), "A"],
    )
    assert concatenated_observations[1].ack == expected_pending
    assert concatenated_observations[2].ack == expected_applied
    _assert_active(concatenated_observations[2], first)


@pytest.mark.parametrize("rollback", ("STOP", "RESTORE_BASELINE", "TIMEOUT"))
def test_rollback_then_start_matches_reference_parameter_result_and_c_permission_state(
    trace_runner: Path, rollback: str
):
    """Rollback cancels pending P first; post-safe-point START only releases permission."""
    candidate = ParameterCommand("camp-001", 2, 40.0, 0.0, 10.0, 680)
    start = RunCommand("camp-001", "run-001", "START").encode()
    boundary = RuntimeParameterBoundary(BASELINE)
    assert boundary.receive(candidate) is None
    boundary.request_rollback(rollback)
    expected_ack = boundary.apply_pending()

    commands = ["I", "X " + _hex(candidate.encode())]
    if rollback == "TIMEOUT":
        commands.append("T")
    else:
        commands.append("X " + _hex(RunCommand("camp-001", "run-001", rollback).encode()))
    commands.extend(["A", "X " + _hex(start), "Q"])
    observations = _run_trace(trace_runner, commands)

    rollback_request = observations[2]
    safe_point = observations[3]
    start_result = observations[4]
    snapshot = observations[5]
    assert rollback_request.motion_inhibited
    assert safe_point.ack == expected_ack
    assert safe_point.motion_inhibited
    _assert_active(safe_point, BASELINE)
    assert not start_result.motion_inhibited
    _assert_active(start_result, BASELINE)
    _assert_active(snapshot, BASELINE)


@pytest.mark.parametrize("rollback", ("STOP", "RESTORE_BASELINE", "TIMEOUT"))
def test_start_cannot_bypass_an_unfinished_rollback(trace_runner: Path, rollback: str):
    """A START before the safe point cannot clear a requested rollback."""
    candidate = ParameterCommand("camp-001", 2, 40.0, 0.0, 10.0, 680)
    start = RunCommand("camp-001", "run-001", "START").encode()
    commands = ["I", "X " + _hex(candidate.encode())]
    if rollback == "TIMEOUT":
        commands.append("T")
    else:
        commands.append("X " + _hex(RunCommand("camp-001", "run-001", rollback).encode()))
    commands.extend(["X " + _hex(start), "A", "Q"])
    observations = _run_trace(trace_runner, commands)
    safe_point = observations[4]
    snapshot = observations[5]
    assert safe_point.ack == ParameterAck("camp-001", 2, "REJECTED", rollback)
    assert safe_point.motion_inhibited
    _assert_active(safe_point, BASELINE)
    assert snapshot.motion_inhibited
    _assert_active(snapshot, BASELINE)


def test_seeded_malformed_corpus_preserves_stopped_baseline_and_never_applies(trace_runner: Path):
    """Every reproducible malformed raw-byte input preserves inhibit and baseline state."""
    global CORPUS_DIGEST_SHA256
    stop = RunCommand("camp-001", "run-001", "STOP").encode()
    cases = _invalid_corpus()
    assert len(cases) >= 40

    # Compute and pin the corpus digest for reproducibility
    digest = hashlib.sha256()
    for case in cases:
        digest.update(case.name.encode("ascii"))
        digest.update(case.payload)
    actual_digest = digest.hexdigest()
    if CORPUS_DIGEST_SHA256 is None:
        CORPUS_DIGEST_SHA256 = actual_digest
    assert CORPUS_DIGEST_SHA256 == actual_digest, (
        "corpus changed from pinned digest {0} to {1}".format(
            CORPUS_DIGEST_SHA256, actual_digest
        )
    )

    for case in cases:
        observations = _run_trace(
            trace_runner,
            ["I", "X " + _hex(stop), "A", "X " + _hex(case.payload), "A", "Q"],
        )
        stopped, received, safe_point, snapshot = observations[2:]
        assert stopped.motion_inhibited, case.name
        _assert_active(stopped, BASELINE)
        for observation in (received, safe_point, snapshot):
            assert observation.motion_inhibited, case.name
            _assert_no_applied_and_baseline(observation)


def test_python_parser_rejects_ascii_malformed_corpus_members():
    """Malformed ASCII frames are rejected before Python can model an unsafe update."""
    for case in _invalid_corpus():
        try:
            text = case.payload.decode("ascii")
        except UnicodeDecodeError:
            continue
        with pytest.raises(ProtocolError):
            parse_command(text)
