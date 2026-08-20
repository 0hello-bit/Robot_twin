"""Identity and provenance primitives for cross-clock observations.

An exchange sequence correlates one Q/T transaction.  It is not an identity
for every timestamp inside that transaction.  Each boundary therefore gets a
distinct event id, event kind, clock domain, observed time, age, and validity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


CLOCK_DOMAIN_MCU_MONOTONIC_MS = "stm32_monotonic_ms"
CLOCK_DOMAIN_PC_MONOTONIC_NS = "pc_monotonic_ns"

EVENT_Q_UART_RX_ISR = "q_uart_rx_isr_observed"
EVENT_Q_PARSE_DONE = "q_parse_done"
EVENT_T_TRANSACTION_STARTED = "t_cipsend_transaction_started"
EVENT_T_PAYLOAD_GENERATED = "t_payload_generated"
EVENT_PC_Q_SENT = "pc_q_sent"
EVENT_PC_T_RECEIVED = "pc_t_received"

OBSERVED_BOUNDARY = "observed_boundary"
DELAYED_BOUNDARY = "delayed_boundary"
REPORTED_BOUNDARY = "reported_boundary"
UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class ClockExchangeIdentity:
    """Stable correlation identity for one transport exchange."""

    transport: str
    sequence: int
    capture_id: str = "local"

    def __post_init__(self) -> None:
        if not isinstance(self.transport, str) or not self.transport:
            raise ValueError("transport must be a non-empty string")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("sequence must be an integer")
        if self.sequence <= 0:
            raise ValueError("sequence must be positive")
        if (
            not isinstance(self.capture_id, str)
            or not self.capture_id
            or len(self.capture_id) > 64
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "abcdefghijklmnopqrstuvwxyz0123456789-_"
                for character in self.capture_id
            )
        ):
            raise ValueError(
                "capture_id must contain only ASCII letters, digits, hyphen, or underscore"
            )

    @property
    def exchange_id(self) -> str:
        if self.capture_id == "local":
            # Preserve the replay identity used by existing local fixtures.
            return "{0}:clock:{1}".format(self.transport, self.sequence)
        return "{0}:clock:{1}:{2}".format(
            self.transport, self.sequence, self.capture_id
        )

    def event(self, event_kind: str) -> str:
        if not isinstance(event_kind, str) or not event_kind:
            raise ValueError("event_kind must be a non-empty string")
        return "{0}:{1}".format(self.exchange_id, event_kind)


@dataclass(frozen=True)
class ClockEvent:
    """One named event boundary, never a generic timestamp value."""

    event_id: str
    sequence: int
    source_id: str
    event_kind: str
    clock_domain: str
    event_time: int
    observed_time: Optional[int]
    data_age: Optional[int]
    validity: str
    uncertainty: Optional[int]
    causal_parent_id: Optional[str]
    transport: str = "tcp"
    capture_id: str = "local"

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError("event_id must be a non-empty string")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("sequence must be an integer")
        if self.sequence <= 0:
            raise ValueError("sequence must be positive")
        for field_name in ("source_id", "event_kind", "clock_domain"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError("{0} must be a non-empty string".format(field_name))
        identity = ClockExchangeIdentity(
            transport=self.transport,
            sequence=self.sequence,
            capture_id=self.capture_id,
        )
        if self.event_id != identity.event(self.event_kind):
            raise ValueError(
                "event_id must identify the same exchange scope and event_kind"
            )
        if self.causal_parent_id is not None:
            if not isinstance(self.causal_parent_id, str) or not self.causal_parent_id:
                raise ValueError("causal_parent_id must be a non-empty event identity")
            if not self.causal_parent_id.startswith(identity.exchange_id + ":"):
                raise ValueError(
                    "causal_parent_id must identify the same exchange scope"
                )
            if self.causal_parent_id == self.event_id:
                raise ValueError("causal_parent_id cannot identify the event itself")
        for field_name in ("event_time", "observed_time", "data_age", "uncertainty"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise ValueError("{0} must be an integer or None".format(field_name))
        if self.event_time < 0:
            raise ValueError("event_time must be non-negative")
        if self.observed_time is not None and self.observed_time < 0:
            raise ValueError("observed_time must be non-negative")
        if self.data_age is not None and self.data_age < 0:
            raise ValueError("data_age must be non-negative")
        if self.uncertainty is not None and self.uncertainty < 0:
            raise ValueError("uncertainty must be non-negative")
        if self.validity not in {
            OBSERVED_BOUNDARY,
            DELAYED_BOUNDARY,
            REPORTED_BOUNDARY,
            UNCLASSIFIED,
        }:
            raise ValueError("validity is not a supported clock-event state")
        if self.validity == DELAYED_BOUNDARY and self.data_age is None:
            raise ValueError("delayed boundary requires data_age")
        if self.validity == DELAYED_BOUNDARY:
            if self.observed_time is None:
                raise ValueError("delayed boundary requires observed_time")
            if self.observed_time < self.event_time:
                raise ValueError("observed_time must be >= event_time")
            if self.observed_time - self.event_time != self.data_age:
                raise ValueError("data_age must equal observed_time - event_time")
        if self.validity == OBSERVED_BOUNDARY:
            if self.observed_time != self.event_time or self.data_age != 0:
                raise ValueError(
                    "observed_boundary requires observed_time == event_time "
                    "and data_age == 0"
                )
        if self.validity == REPORTED_BOUNDARY:
            if self.observed_time is not None or self.data_age is not None:
                raise ValueError(
                    "reported boundary cannot claim a same-domain observation age"
                )


def build_clock_event(
    *,
    sequence: int,
    event_kind: str,
    event_time: int,
    source_id: str,
    observed_time: Optional[int],
    data_age: Optional[int],
    uncertainty: Optional[int],
    validity: str,
    causal_parent_id: Optional[str],
    transport: str = "tcp",
    capture_id: str = "local",
    clock_domain: str = CLOCK_DOMAIN_MCU_MONOTONIC_MS,
) -> ClockEvent:
    """Construct an event with an identity derived from its exchange."""

    identity = ClockExchangeIdentity(
        transport=transport, sequence=sequence, capture_id=capture_id
    )
    return ClockEvent(
        event_id=identity.event(event_kind),
        sequence=sequence,
        source_id=source_id,
        event_kind=event_kind,
        clock_domain=clock_domain,
        event_time=event_time,
        observed_time=observed_time,
        data_age=data_age,
        validity=validity,
        uncertainty=uncertainty,
        causal_parent_id=causal_parent_id,
        transport=transport,
        capture_id=capture_id,
    )


__all__ = [
    "CLOCK_DOMAIN_MCU_MONOTONIC_MS",
    "CLOCK_DOMAIN_PC_MONOTONIC_NS",
    "DELAYED_BOUNDARY",
    "REPORTED_BOUNDARY",
    "EVENT_Q_PARSE_DONE",
    "EVENT_Q_UART_RX_ISR",
    "EVENT_PC_Q_SENT",
    "EVENT_PC_T_RECEIVED",
    "EVENT_T_PAYLOAD_GENERATED",
    "EVENT_T_TRANSACTION_STARTED",
    "OBSERVED_BOUNDARY",
    "UNCLASSIFIED",
    "ClockEvent",
    "ClockExchangeIdentity",
    "build_clock_event",
]
