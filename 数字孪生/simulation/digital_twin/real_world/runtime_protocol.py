"""Strict ASCII protocol for bounded runtime line-following PID updates.

This module has no transport side effects.  It validates and serializes the
frames that a later bridge task may send to the STM32 safety boundary.
"""

from dataclasses import dataclass
import math
import re


MIN_SPEED_MAX = 260
MAX_SPEED_MAX = 680
SPEED_STEP_MAX = 100
KP_MIN = 20.0
KP_MAX = 50.0
KP_STEP_MAX = 5.0
KI_MIN = 0.0
KI_MAX = 5.0
KI_STEP_MAX = 1.0
KD_MIN = 5.0
KD_MAX = 20.0
KD_STEP_MAX = 3.0
MAX_IDENTIFIER_LENGTH = 16
MAX_VERSION = 0xFFFFFFFF
MAX_COMMAND_BODY_BYTES = 96
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9-]+$")
_RUN_ACTIONS = frozenset(("START", "STOP", "RESTORE_BASELINE"))
_ACK_OUTCOMES = frozenset(("APPLIED", "REJECTED"))


class ProtocolError(ValueError):
    """Raised when a runtime-control frame is not safe or well-formed."""


def xor_checksum(body):
    """Return the XOR of the ASCII body, excluding the delimiter before checksum."""
    try:
        encoded = body.encode("ascii")
    except UnicodeEncodeError as error:
        raise ProtocolError("frame must be ASCII") from error
    value = 0
    for byte in encoded:
        value ^= byte
    return "{0:02X}".format(value)


def frame(body):
    """Append the protocol checksum and mandatory newline to an ASCII body."""
    return "{0},{1}\n".format(body, xor_checksum(body))


def _validate_identifier(value, name):
    if (not isinstance(value, str) or not value or len(value) > MAX_IDENTIFIER_LENGTH
            or not _IDENTIFIER_RE.fullmatch(value)):
        raise ProtocolError("{0} must contain only ASCII letters, digits, or hyphen".format(name))


def _validate_positive_integer(value, name):
    if (isinstance(value, bool) or not isinstance(value, int) or value <= 0
            or value > MAX_VERSION):
        raise ProtocolError("{0} must be a positive integer".format(name))


def _validate_finite(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProtocolError("{0} must be finite".format(name))
    if minimum is not None and value < minimum:
        raise ProtocolError("{0} must be at least {1}".format(name, minimum))


def _validate_speed(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError("speed_max must be an integer")
    if value < MIN_SPEED_MAX or value > MAX_SPEED_MAX:
        raise ProtocolError("speed_max must be within {0}..{1}".format(MIN_SPEED_MAX, MAX_SPEED_MAX))


def _validate_gain(value, name, minimum, maximum):
    _validate_finite(value, name)
    if value < minimum or value > maximum:
        raise ProtocolError("{0} must be within {1}..{2}".format(name, minimum, maximum))


def _validate_parameter_command(command):
    _validate_identifier(command.campaign_id, "campaign_id")
    _validate_positive_integer(command.version, "version")
    _validate_gain(command.kp, "kp", KP_MIN, KP_MAX)
    _validate_gain(command.ki, "ki", KI_MIN, KI_MAX)
    _validate_gain(command.kd, "kd", KD_MIN, KD_MAX)
    _validate_speed(command.speed_max)


def _validate_step(candidate, active, field, limit):
    if abs(getattr(candidate, field) - getattr(active, field)) > limit:
        raise ProtocolError("{0} step exceeds firmware limit".format(field))


def validate_parameter_update(candidate, active):
    """Reject a bounded parameter update that exceeds any one-step safety limit."""
    if not isinstance(candidate, ParameterCommand) or not isinstance(active, ParameterCommand):
        raise ProtocolError("parameter update requires ParameterCommand values")
    _validate_parameter_command(candidate)
    _validate_parameter_command(active)
    _validate_step(candidate, active, "kp", KP_STEP_MAX)
    _validate_step(candidate, active, "ki", KI_STEP_MAX)
    _validate_step(candidate, active, "kd", KD_STEP_MAX)
    _validate_step(candidate, active, "speed_max", SPEED_STEP_MAX)


def _format_number(value):
    return "{0:.9g}".format(value)


def _validate_command_body(body):
    try:
        body_bytes = body.encode("ascii")
    except UnicodeEncodeError as error:
        raise ProtocolError("frame must be ASCII") from error
    if len(body_bytes) > MAX_COMMAND_BODY_BYTES:
        raise ProtocolError("command frame exceeds firmware line limit")


def _split_and_verify(text, expected_type, field_count):
    if not isinstance(text, str) or not text.endswith("\n") or text.count("\n") != 1:
        raise ProtocolError("frame must be newline-terminated")
    if "\r" in text:
        raise ProtocolError("frame must use LF only")
    try:
        text.encode("ascii")
    except UnicodeEncodeError as error:
        raise ProtocolError("frame must be ASCII") from error
    fields = text[:-1].split(",")
    if len(fields) != field_count:
        raise ProtocolError("wrong field count")
    if fields[0] != expected_type:
        raise ProtocolError("unexpected frame type")
    checksum = fields[-1]
    if not re.fullmatch(r"[0-9A-F]{2}", checksum):
        raise ProtocolError("checksum must be two uppercase hexadecimal digits")
    body = ",".join(fields[:-1])
    if xor_checksum(body) != checksum:
        raise ProtocolError("checksum mismatch")
    return fields[:-1]


def _parse_positive_integer(text, name):
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise ProtocolError("{0} must be a positive integer".format(name))
    value = int(text)
    _validate_positive_integer(value, name)
    return value


def _parse_finite(text, name, minimum=None):
    try:
        value = float(text)
    except ValueError as error:
        raise ProtocolError("{0} must be numeric".format(name)) from error
    _validate_finite(value, name, minimum)
    return value


@dataclass(frozen=True)
class ParameterCommand:
    campaign_id: str
    version: int
    kp: float
    ki: float
    kd: float
    speed_max: int

    def encode(self):
        _validate_parameter_command(self)
        body = "P,{0},{1},{2},{3},{4},{5}".format(
            self.campaign_id,
            self.version,
            _format_number(self.kp),
            _format_number(self.ki),
            _format_number(self.kd),
            self.speed_max,
        )
        _validate_command_body(body)
        return frame(body)


@dataclass(frozen=True)
class RunCommand:
    campaign_id: str
    run_id: str
    action: str

    def encode(self):
        _validate_identifier(self.campaign_id, "campaign_id")
        _validate_identifier(self.run_id, "run_id")
        if self.action not in _RUN_ACTIONS:
            raise ProtocolError("invalid run action")
        body = "R,{0},{1},{2}".format(self.campaign_id, self.run_id, self.action)
        _validate_command_body(body)
        return frame(body)


@dataclass(frozen=True)
class ParameterAck:
    campaign_id: str
    version: int
    outcome: str
    reason: str


@dataclass(frozen=True)
class RunStatus:
    campaign_id: str
    run_id: str
    state: str
    reason: str
    tick_ms: int


class RuntimeParameterBoundary:
    """Reference safe-point gate with direct terminal results for every P command."""

    def __init__(self, baseline):
        if not isinstance(baseline, ParameterCommand):
            raise ProtocolError("baseline must be a ParameterCommand")
        _validate_parameter_command(baseline)
        self._baseline = baseline
        self._active = baseline
        self._pending = None
        self._rollback_reason = None

    @property
    def active(self):
        return self._active

    def receive(self, command):
        """Accept one candidate or return its direct, correlatable rejection ACK."""
        if not isinstance(command, ParameterCommand):
            raise ProtocolError("runtime boundary accepts ParameterCommand")
        try:
            _validate_parameter_command(command)
            validate_parameter_update(command, self._active)
        except ProtocolError as error:
            return ParameterAck(command.campaign_id, command.version, "REJECTED", str(error).split()[0])
        if self._rollback_reason is not None:
            return ParameterAck(command.campaign_id, command.version, "REJECTED", "INHIBITED")
        if self._pending is not None:
            return ParameterAck(command.campaign_id, command.version, "REJECTED", "PENDING")
        self._pending = command
        return None

    def request_rollback(self, reason):
        if reason not in ("STOP", "RESTORE_BASELINE", "TIMEOUT"):
            raise ProtocolError("invalid rollback reason")
        self._rollback_reason = reason

    def apply_pending(self):
        """Apply the pending command or return its cancellation/APPLIED terminal ACK."""
        if self._rollback_reason is not None:
            pending = self._pending
            reason = self._rollback_reason
            self._active = self._baseline
            self._pending = None
            self._rollback_reason = None
            if pending is not None:
                return ParameterAck(pending.campaign_id, pending.version, "REJECTED", reason)
            return None
        if self._pending is None:
            return None
        applied = self._pending
        self._active = applied
        self._pending = None
        return ParameterAck(applied.campaign_id, applied.version, "APPLIED", "APPLIED")


def parse_command(text):
    """Parse a complete P or R frame after verifying every protocol guard."""
    if not isinstance(text, str) or not text:
        raise ProtocolError("frame must be newline-terminated")
    if not text.endswith("\n") or "\r" in text:
        raise ProtocolError("frame must use LF only")
    try:
        _validate_command_body(text[:-1])
    except ProtocolError:
        raise
    frame_type = text[0]
    if frame_type == "P":
        fields = _split_and_verify(text, "P", 8)
        campaign_id = fields[1]
        _validate_identifier(campaign_id, "campaign_id")
        version = _parse_positive_integer(fields[2], "version")
        kp = _parse_finite(fields[3], "kp")
        ki = _parse_finite(fields[4], "ki", KI_MIN)
        kd = _parse_finite(fields[5], "kd")
        if not re.fullmatch(r"[0-9]+", fields[6]):
            raise ProtocolError("speed_max must be an integer")
        speed_max = int(fields[6])
        command = ParameterCommand(campaign_id, version, kp, ki, kd, speed_max)
        _validate_parameter_command(command)
        return command
    if frame_type == "R":
        fields = _split_and_verify(text, "R", 5)
        campaign_id, run_id, action = fields[1], fields[2], fields[3]
        _validate_identifier(campaign_id, "campaign_id")
        _validate_identifier(run_id, "run_id")
        if action not in _RUN_ACTIONS:
            raise ProtocolError("invalid run action")
        return RunCommand(campaign_id, run_id, action)
    raise ProtocolError("unexpected frame type")


def parse_ack(text):
    """Parse a version-correlated firmware acknowledgement."""
    fields = _split_and_verify(text, "A", 6)
    campaign_id, version_text, outcome, reason = fields[1], fields[2], fields[3], fields[4]
    _validate_identifier(campaign_id, "campaign_id")
    version = _parse_positive_integer(version_text, "version")
    if outcome not in _ACK_OUTCOMES:
        raise ProtocolError("invalid acknowledgement outcome")
    if not reason or "," in reason:
        raise ProtocolError("invalid acknowledgement reason")
    return ParameterAck(campaign_id, version, outcome, reason)


def parse_status(text):
    """Parse a run-status evidence frame."""
    fields = _split_and_verify(text, "S", 7)
    campaign_id, run_id, state, reason, tick_text = fields[1], fields[2], fields[3], fields[4], fields[5]
    _validate_identifier(campaign_id, "campaign_id")
    _validate_identifier(run_id, "run_id")
    if not state or not reason or "," in state or "," in reason:
        raise ProtocolError("invalid status fields")
    if not re.fullmatch(r"[0-9]+", tick_text):
        raise ProtocolError("tick_ms must be a non-negative integer")
    return RunStatus(campaign_id, run_id, state, reason, int(tick_text))
