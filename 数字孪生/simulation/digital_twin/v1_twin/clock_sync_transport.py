"""Offline contract and evidence accounting for ClockSync transport A/B runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


_SUPPORTED_TRANSPORTS = frozenset(("tcp", "udp"))
_CLOCK_SYNC_MODE = "clock_sync_only"
_PAYLOAD_CONTRACT = "q_t_v1"
_PC_CLOCK_SOURCE = "perf_counter_ns"
_UDP_IPD_HEADER_MODE = "link_id_length"


class ClockSyncTransportContractError(ValueError):
    """Raised when an offline transport contract is malformed or unsafe."""


def _require_bool(value: Any, name: str) -> None:
    if not isinstance(value, bool):
        raise ClockSyncTransportContractError(
            "{0} must be a boolean".format(name)
        )


def _require_nonnegative_int(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ClockSyncTransportContractError(
            "{0} must be a non-negative integer".format(name)
        )


def _require_positive_int(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ClockSyncTransportContractError(
            "{0} must be a positive integer".format(name)
        )


def _has_at_gmr_version_line(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    for line in value.splitlines():
        label, separator, version = line.partition(":")
        if (separator and label.strip().casefold() == "at version" and
                version.strip()):
            return True
    return False


def _has_explicit_capability_source(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class EspUdpCapabilityEvidence:
    """Captured ESP facts required before selecting the UDP profile."""

    at_gmr: Optional[str] = None
    cipmux: Optional[int] = None
    cipmode: Optional[int] = None
    udp_supported: Optional[bool] = None
    ipd_header_mode: Optional[str] = None
    udp_capability_source: Optional[str] = None

    def missing_requirements(self) -> List[str]:
        missing = []
        if not _has_at_gmr_version_line(self.at_gmr):
            missing.append("at_gmr")
        if type(self.cipmux) is not int or self.cipmux != 1:
            missing.append("cipmux=1")
        if type(self.cipmode) is not int or self.cipmode != 0:
            missing.append("cipmode=0")
        if self.udp_supported is not True:
            missing.append("udp_supported=true")
        elif not _has_explicit_capability_source(self.udp_capability_source):
            missing.append("udp_capability_source")
        if self.ipd_header_mode != _UDP_IPD_HEADER_MODE:
            missing.append("ipd_header_mode=link_id_length")
        return missing

    def to_dict(self) -> Dict[str, Any]:
        return {
            "at_gmr": self.at_gmr,
            "cipmux": self.cipmux,
            "cipmode": self.cipmode,
            "udp_supported": self.udp_supported,
            "ipd_header_mode": self.ipd_header_mode,
            "udp_capability_source": self.udp_capability_source,
        }


@dataclass(frozen=True)
class ClockSyncTransportProfile:
    """Immutable run contract shared by the TCP and UDP ClockSync A/B."""

    transport: str
    mode: str = _CLOCK_SYNC_MODE
    payload_contract: str = _PAYLOAD_CONTRACT
    single_outstanding: bool = True
    primary_retries: bool = False
    pc_clock_source: str = _PC_CLOCK_SOURCE
    telemetry_migrated: bool = False
    health_migrated: bool = False
    control_migrated: bool = False

    def validate(self) -> None:
        if (not isinstance(self.transport, str) or
                self.transport not in _SUPPORTED_TRANSPORTS):
            raise ClockSyncTransportContractError(
                "transport must be tcp or udp"
            )
        if self.mode != _CLOCK_SYNC_MODE:
            raise ClockSyncTransportContractError(
                "mode must be clock_sync_only"
            )
        if self.payload_contract != _PAYLOAD_CONTRACT:
            raise ClockSyncTransportContractError(
                "payload_contract must be q_t_v1"
            )
        if self.single_outstanding is not True:
            raise ClockSyncTransportContractError(
                "single_outstanding must be true"
            )
        if self.primary_retries is not False:
            raise ClockSyncTransportContractError(
                "primary_retries must be false"
            )
        if self.pc_clock_source != _PC_CLOCK_SOURCE:
            raise ClockSyncTransportContractError(
                "pc_clock_source must be perf_counter_ns"
            )
        for name in (
            "single_outstanding",
            "primary_retries",
            "telemetry_migrated",
            "health_migrated",
            "control_migrated",
        ):
            _require_bool(getattr(self, name), name)
        for name in (
            "telemetry_migrated",
            "health_migrated",
            "control_migrated",
        ):
            if getattr(self, name):
                raise ClockSyncTransportContractError(
                    "{0} must be false".format(name)
                )

    def readiness(
        self,
        capabilities: Optional[EspUdpCapabilityEvidence] = None,
    ) -> Dict[str, Any]:
        self.validate()
        if self.transport == "tcp":
            return {
                "verdict": "READY",
                "transport": "tcp",
                "reason": "TCP profile has no UDP capability requirement",
                "missing": [],
            }
        if capabilities is None:
            missing = [
                "at_gmr",
                "cipmux=1",
                "cipmode=0",
                "udp_supported=true",
                "ipd_header_mode=link_id_length",
            ]
        elif not isinstance(capabilities, EspUdpCapabilityEvidence):
            raise ClockSyncTransportContractError(
                "UDP readiness requires EspUdpCapabilityEvidence"
            )
        else:
            missing = capabilities.missing_requirements()
        if missing:
            return {
                "verdict": "INSUFFICIENT EVIDENCE",
                "transport": "udp",
                "reason": "ESP UDP capability evidence is incomplete",
                "missing": list(missing),
            }
        return {
            "verdict": "READY",
            "transport": "udp",
            "reason": "ESP UDP capability evidence is complete",
            "missing": [],
        }

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "transport": self.transport,
            "mode": self.mode,
            "payload_contract": self.payload_contract,
            "single_outstanding": self.single_outstanding,
            "primary_retries": self.primary_retries,
            "pc_clock_source": self.pc_clock_source,
            "telemetry_migrated": self.telemetry_migrated,
            "health_migrated": self.health_migrated,
            "control_migrated": self.control_migrated,
        }


@dataclass(frozen=True)
class ClockSyncTransportObservation:
    """One primary sent sequence and its matched or lost outcome."""

    sequence: int
    pc_tx_ns: int
    matched: bool
    pc_rx_ns: Optional[int] = None
    rtt_transport_ns: Optional[int] = None
    duplicate_count: int = 0
    reordered: bool = False
    late_reply: bool = False
    pc_clock_source: str = _PC_CLOCK_SOURCE

    def __post_init__(self) -> None:
        _require_positive_int(self.sequence, "sequence")
        _require_nonnegative_int(self.pc_tx_ns, "pc_tx_ns")
        _require_bool(self.matched, "matched")
        _require_bool(self.reordered, "reordered")
        _require_bool(self.late_reply, "late_reply")
        _require_nonnegative_int(self.duplicate_count, "duplicate_count")
        if self.pc_clock_source != _PC_CLOCK_SOURCE:
            raise ClockSyncTransportContractError(
                "pc_clock_source must be perf_counter_ns"
            )
        if self.pc_rx_ns is not None:
            _require_nonnegative_int(self.pc_rx_ns, "pc_rx_ns")
            if self.pc_rx_ns < self.pc_tx_ns:
                raise ClockSyncTransportContractError(
                    "pc_rx_ns must not precede pc_tx_ns"
                )
        if self.matched and self.pc_rx_ns is None:
            raise ClockSyncTransportContractError(
                "matched observation requires pc_rx_ns"
            )
        if self.late_reply and self.pc_rx_ns is None:
            raise ClockSyncTransportContractError(
                "late_reply requires pc_rx_ns"
            )
        if self.matched and self.late_reply:
            raise ClockSyncTransportContractError(
                "late_reply cannot be marked matched"
            )
        if self.rtt_transport_ns is not None:
            _require_nonnegative_int(
                self.rtt_transport_ns, "rtt_transport_ns"
            )
            if not self.matched:
                raise ClockSyncTransportContractError(
                    "unmatched observation cannot have rtt_transport_ns"
                )

    @property
    def rtt_total_ns(self) -> Optional[int]:
        if self.pc_rx_ns is None:
            return None
        return self.pc_rx_ns - self.pc_tx_ns

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "pc_tx_ns": self.pc_tx_ns,
            "pc_rx_ns": self.pc_rx_ns,
            "matched": self.matched,
            "rtt_total_ns": self.rtt_total_ns,
            "rtt_transport_ns": self.rtt_transport_ns,
            "duplicate_count": self.duplicate_count,
            "reordered": self.reordered,
            "late_reply": self.late_reply,
            "pc_clock_source": self.pc_clock_source,
        }


def _percentile(values: Sequence[int], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return float(
        ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    )


def summarize_clock_sync_transport(
    observations: Sequence[ClockSyncTransportObservation],
) -> Dict[str, Any]:
    """Summarize every supplied outcome without outlier filtering."""

    items = tuple(observations)
    seen = set()
    for observation in items:
        if not isinstance(observation, ClockSyncTransportObservation):
            raise ClockSyncTransportContractError(
                "observations must contain ClockSyncTransportObservation values"
            )
        if observation.sequence in seen:
            raise ClockSyncTransportContractError(
                "observation sequence must be unique"
            )
        seen.add(observation.sequence)

    matched = tuple(item for item in items if item.matched)
    total_rtt = tuple(
        item.rtt_total_ns for item in matched
        if item.rtt_total_ns is not None
    )
    transport_rtt = tuple(
        item.rtt_transport_ns for item in matched
        if item.rtt_transport_ns is not None
    )
    sent_count = len(items)
    lost_count = sent_count - len(matched)
    return {
        "sent_count": sent_count,
        "matched_count": len(matched),
        "lost_count": lost_count,
        "loss_ratio": (float(lost_count) / sent_count
                        if sent_count else 0.0),
        "duplicate_count": sum(
            item.duplicate_count for item in items
        ),
        "reordered_count": sum(
            1 for item in items if item.reordered
        ),
        "late_reply_count": sum(
            1 for item in items if item.late_reply
        ),
        "total_rtt_sample_count": len(total_rtt),
        "total_rtt_p50_ns": _percentile(total_rtt, 50.0),
        "total_rtt_p95_ns": _percentile(total_rtt, 95.0),
        "total_rtt_max_ns": max(total_rtt) if total_rtt else None,
        "transport_rtt_sample_count": len(transport_rtt),
        "transport_rtt_p50_ns": _percentile(transport_rtt, 50.0),
        "transport_rtt_p95_ns": _percentile(transport_rtt, 95.0),
        "transport_rtt_max_ns": (
            max(transport_rtt) if transport_rtt else None
        ),
    }


__all__ = [
    "ClockSyncTransportContractError",
    "ClockSyncTransportObservation",
    "ClockSyncTransportProfile",
    "EspUdpCapabilityEvidence",
    "summarize_clock_sync_transport",
]
