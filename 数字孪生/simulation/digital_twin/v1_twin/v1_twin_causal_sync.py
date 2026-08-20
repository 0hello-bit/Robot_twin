"""Evidence-traceable PC/MCU clock exchange and causal sync metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

import numpy as np

from v1_twin.clock_event_identity import (
    CLOCK_DOMAIN_MCU_MONOTONIC_MS,
    CLOCK_DOMAIN_PC_MONOTONIC_NS,
    EVENT_PC_Q_SENT,
    EVENT_PC_T_RECEIVED,
    EVENT_Q_PARSE_DONE,
    EVENT_Q_UART_RX_ISR,
    EVENT_T_PAYLOAD_GENERATED,
    EVENT_T_TRANSACTION_STARTED,
    OBSERVED_BOUNDARY,
    REPORTED_BOUNDARY,
    ClockEvent,
    ClockExchangeIdentity,
)


_EXCHANGE_FIELDS = (
    "capture_id",
    "observation_id",
    "sequence",
    "pc_tx_ns",
    "pc_tx_event_id",
    "pc_tx_event_kind",
    "pc_tx_event_clock_domain",
    "pc_tx_event_validity",
    "pc_tx_event_uncertainty_ns",
    "pc_tx_event_observed_ns",
    "pc_tx_event_data_age_ns",
    "q_event_id",
    "q_event_tick_ms",
    "q_event_observed_tick_ms",
    "q_event_data_age_ms",
    "t_event_tick_ms",
    "t_event_observed_tick_ms",
    "t_event_data_age_ms",
    "pc_rx_ns",
    "pc_rx_event_id",
    "pc_rx_event_kind",
    "pc_rx_event_clock_domain",
    "pc_rx_event_validity",
    "pc_rx_event_uncertainty_ns",
    "pc_rx_event_observed_ns",
    "pc_rx_event_data_age_ns",
    "q_event_kind",
    "q_event_clock_domain",
    "q_event_validity",
    "q_event_uncertainty_ns",
    "q_parse_event_id",
    "q_parse_causal_parent_event_id",
    "q_parse_done_tick_ms",
    "q_parse_event_kind",
    "q_parse_event_clock_domain",
    "q_parse_event_validity",
    "q_parse_event_uncertainty_ns",
    "q_parse_event_observed_tick_ms",
    "q_parse_event_data_age_ms",
    "q_parse_role",
    "t_event_id",
    "t_event_kind",
    "t_event_clock_domain",
    "t_event_validity",
    "t_event_uncertainty_ns",
    "t_payload_event_id",
    "t_payload_causal_parent_event_id",
    "t_payload_generated_tick_ms",
    "t_payload_event_kind",
    "t_payload_event_clock_domain",
    "t_payload_event_validity",
    "t_payload_event_uncertainty_ns",
    "t_payload_event_observed_tick_ms",
    "t_payload_event_data_age_ms",
    "t_payload_role",
    "timestamp_schema_version",
)


def _required_int(record: Mapping[str, Any], field: str) -> int:
    if field not in record:
        raise ValueError("missing exchange field: {0}".format(field))
    value = record[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("exchange field {0} must be an integer".format(field))
    return int(value)


def _optional_int(record: Mapping[str, Any], field: str) -> int | None:
    if field not in record:
        raise ValueError("missing exchange field: {0}".format(field))
    value = record[field]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("exchange field {0} must be an integer or null".format(field))
    return int(value)


def _required_text(record: Mapping[str, Any], field: str) -> str:
    if field not in record:
        raise ValueError("missing exchange field: {0}".format(field))
    value = record[field]
    if not isinstance(value, str) or not value:
        raise ValueError("exchange field {0} must be a non-empty string".format(field))
    return value


@dataclass(frozen=True)
class ClockExchangeSample:
    """One NTP-style PC -> MCU -> PC clock exchange.

    ``pc_tx_ns`` and ``pc_rx_ns`` use the host monotonic clock.  The MCU
    fields use the firmware monotonic millisecond counter.  The sample keeps
    both endpoints so path delay is measurable instead of being folded into a
    fake per-telemetry receive timestamp.
    """

    sequence: int
    pc_tx_ns: int
    q_event_tick_ms: int
    t_event_tick_ms: int
    pc_rx_ns: int
    capture_id: str = "local"
    pc_tx_event_kind: str = EVENT_PC_Q_SENT
    pc_tx_event_clock_domain: str = CLOCK_DOMAIN_PC_MONOTONIC_NS
    pc_tx_event_validity: str = OBSERVED_BOUNDARY
    pc_tx_event_uncertainty_ns: int | None = None
    pc_tx_event_observed_ns: int | None = None
    pc_tx_event_data_age_ns: int = 0
    q_event_kind: str = EVENT_Q_UART_RX_ISR
    q_event_observed_tick_ms: int | None = None
    q_event_data_age_ms: int = 0
    t_event_kind: str = EVENT_T_TRANSACTION_STARTED
    t_event_observed_tick_ms: int | None = None
    t_event_data_age_ms: int = 0
    pc_rx_event_kind: str = EVENT_PC_T_RECEIVED
    pc_rx_event_clock_domain: str = CLOCK_DOMAIN_PC_MONOTONIC_NS
    pc_rx_event_validity: str = OBSERVED_BOUNDARY
    pc_rx_event_uncertainty_ns: int | None = None
    pc_rx_event_observed_ns: int | None = None
    pc_rx_event_data_age_ns: int = 0
    timestamp_schema_version: int = 2
    q_parse_done_tick_ms: int | None = None
    q_parse_causal_parent_event_id: str | None = None
    t_payload_generated_tick_ms: int | None = None
    q_parse_event_kind: str = EVENT_Q_PARSE_DONE
    q_parse_event_clock_domain: str = CLOCK_DOMAIN_MCU_MONOTONIC_MS
    q_parse_event_validity: str = REPORTED_BOUNDARY
    q_parse_event_uncertainty_ns: int | None = None
    q_parse_event_observed_tick_ms: int | None = None
    q_parse_event_data_age_ms: int | None = None
    q_parse_role: str = "diagnostic_only"
    t_payload_event_kind: str = EVENT_T_PAYLOAD_GENERATED
    t_payload_event_clock_domain: str = CLOCK_DOMAIN_MCU_MONOTONIC_MS
    t_payload_event_validity: str = REPORTED_BOUNDARY
    t_payload_event_uncertainty_ns: int | None = None
    t_payload_causal_parent_event_id: str | None = None
    t_payload_event_observed_tick_ms: int | None = None
    t_payload_event_data_age_ms: int | None = None
    t_payload_role: str = "diagnostic_only"
    q_event_validity: str = OBSERVED_BOUNDARY
    t_event_validity: str = OBSERVED_BOUNDARY
    q_event_uncertainty_ns: int | None = None
    t_event_uncertainty_ns: int | None = None

    def __post_init__(self) -> None:
        values = {
            "sequence": self.sequence,
            "pc_tx_ns": self.pc_tx_ns,
            "q_event_tick_ms": self.q_event_tick_ms,
            "t_event_tick_ms": self.t_event_tick_ms,
            "pc_rx_ns": self.pc_rx_ns,
            "timestamp_schema_version": self.timestamp_schema_version,
        }
        for field, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    "exchange field {0} must be an integer".format(field)
                )
        if self.sequence <= 0:
            raise ValueError("sequence must be positive")
        if self.pc_tx_ns < 0:
            raise ValueError("pc_tx_ns must be non-negative")
        if self.q_event_tick_ms < 0 or self.t_event_tick_ms < 0:
            raise ValueError("MCU ticks must be non-negative")
        if self.pc_rx_ns < self.pc_tx_ns:
            raise ValueError("pc_rx_ns must be >= pc_tx_ns")
        ClockExchangeIdentity(
            transport="tcp", sequence=self.sequence, capture_id=self.capture_id
        )
        if self.q_parse_causal_parent_event_id is None:
            object.__setattr__(
                self,
                "q_parse_causal_parent_event_id",
                self.q_event_id,
            )
        if self.t_payload_causal_parent_event_id is None:
            object.__setattr__(
                self,
                "t_payload_causal_parent_event_id",
                self.t_event_id,
            )
        if self.q_parse_causal_parent_event_id != self.q_event_id:
            raise ValueError(
                "q_parse causal parent must identify the Q UART event"
            )
        if self.t_payload_causal_parent_event_id != self.t_event_id:
            raise ValueError(
                "t_payload causal parent must identify the T transaction event"
            )
        if self.timestamp_schema_version != 2:
            raise ValueError("causal fit requires timestamp schema version 2")
        if self.pc_tx_event_kind != EVENT_PC_Q_SENT:
            raise ValueError("causal fit requires the PC Q-send event")
        if self.pc_rx_event_kind != EVENT_PC_T_RECEIVED:
            raise ValueError("causal fit requires the PC T-receive event")
        if self.pc_tx_event_clock_domain != CLOCK_DOMAIN_PC_MONOTONIC_NS:
            raise ValueError("PC Q-send clock domain is not explicit")
        if self.pc_rx_event_clock_domain != CLOCK_DOMAIN_PC_MONOTONIC_NS:
            raise ValueError("PC T-receive clock domain is not explicit")
        if self.pc_tx_event_validity != OBSERVED_BOUNDARY:
            raise ValueError("PC Q-send is not an observed boundary")
        if self.pc_rx_event_validity != OBSERVED_BOUNDARY:
            raise ValueError("PC T-receive is not an observed boundary")
        if self.q_event_kind != EVENT_Q_UART_RX_ISR:
            raise ValueError("causal fit requires the UART ISR Q event")
        if self.t_event_kind != EVENT_T_TRANSACTION_STARTED:
            raise ValueError("causal fit requires the transaction-start T event")
        if self.q_event_validity != OBSERVED_BOUNDARY:
            raise ValueError("Q event is not a fit-eligible observed boundary")
        if self.t_event_validity != OBSERVED_BOUNDARY:
            raise ValueError("T event is not a fit-eligible observed boundary")
        if self.q_parse_event_kind != EVENT_Q_PARSE_DONE:
            raise ValueError("Q parse event kind is not explicit")
        if self.t_payload_event_kind != EVENT_T_PAYLOAD_GENERATED:
            raise ValueError("T payload event kind is not explicit")
        if self.q_parse_event_clock_domain != CLOCK_DOMAIN_MCU_MONOTONIC_MS:
            raise ValueError("Q parse event clock domain is not explicit")
        if self.t_payload_event_clock_domain != CLOCK_DOMAIN_MCU_MONOTONIC_MS:
            raise ValueError("T payload event clock domain is not explicit")
        if self.q_parse_event_validity != REPORTED_BOUNDARY:
            raise ValueError("Q parse event must be a reported boundary")
        if self.t_payload_event_validity != REPORTED_BOUNDARY:
            raise ValueError("T payload event must be a reported boundary")
        if self.q_parse_role != "diagnostic_only":
            raise ValueError("Q parse event cannot be a causal-fit endpoint")
        if self.t_payload_role != "diagnostic_only":
            raise ValueError("T payload event cannot be a causal-fit endpoint")
        if self.t_event_tick_ms < self.q_event_tick_ms:
            raise ValueError("t_event_tick_ms must be >= q_event_tick_ms")
        if self.q_parse_done_tick_ms is None:
            raise ValueError("q_parse_done_tick_ms is required for schema v2")
        if self.t_payload_generated_tick_ms is None:
            raise ValueError(
                "t_payload_generated_tick_ms is required for schema v2"
            )
        if self.q_parse_done_tick_ms < self.q_event_tick_ms:
            raise ValueError(
                "q_parse_done_tick_ms must be >= q_event_tick_ms"
            )
        if self.t_event_tick_ms < self.q_parse_done_tick_ms:
            raise ValueError(
                "t_event_tick_ms must be >= q_parse_done_tick_ms"
            )
        if self.t_payload_generated_tick_ms < self.t_event_tick_ms:
            raise ValueError(
                "t_payload_generated_tick_ms must be >= t_event_tick_ms"
            )
        observed_fields = (
            ("pc_tx_event_observed_ns", self.pc_tx_ns),
            ("pc_rx_event_observed_ns", self.pc_rx_ns),
            ("q_event_observed_tick_ms", self.q_event_tick_ms),
            ("t_event_observed_tick_ms", self.t_event_tick_ms),
        )
        for field, event_time in observed_fields:
            observed_time = getattr(self, field)
            if observed_time is None:
                raise ValueError("{0} is required for timestamp provenance".format(field))
            if observed_time != event_time:
                raise ValueError(
                    "{0} cannot be used as an exact event timestamp when delayed".format(
                        field
                    )
                )
        fit_uncertainty_fields = (
            "pc_tx_event_uncertainty_ns",
            "q_event_uncertainty_ns",
            "t_event_uncertainty_ns",
            "pc_rx_event_uncertainty_ns",
        )
        if any(getattr(self, field) is None for field in fit_uncertainty_fields):
            raise ValueError(
                "causal fit requires an independently verified uncertainty bound"
            )
        for field in (
            "q_parse_event_observed_tick_ms",
            "q_parse_event_data_age_ms",
            "t_payload_event_observed_tick_ms",
            "t_payload_event_data_age_ms",
        ):
            if getattr(self, field) is not None:
                raise ValueError(
                    "{0} cannot claim a same-domain age for a reported boundary".format(
                        field
                    )
                )
        for field in (
            "pc_tx_event_uncertainty_ns",
            "pc_tx_event_data_age_ns",
            "q_event_data_age_ms",
            "t_event_data_age_ms",
            "pc_rx_event_uncertainty_ns",
            "pc_rx_event_data_age_ns",
            "q_parse_done_tick_ms",
            "t_payload_generated_tick_ms",
            "q_parse_event_uncertainty_ns",
            "q_parse_event_data_age_ms",
            "t_payload_event_uncertainty_ns",
            "t_payload_event_data_age_ms",
            "q_event_uncertainty_ns",
            "t_event_uncertainty_ns",
        ):
            value = getattr(self, field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise ValueError("{0} must be an integer or None".format(field))
            if value is not None and value < 0:
                raise ValueError("{0} must be non-negative".format(field))
        for field in (
            "pc_tx_event_data_age_ns",
            "pc_rx_event_data_age_ns",
            "q_event_data_age_ms",
            "t_event_data_age_ms",
        ):
            if getattr(self, field) != 0:
                raise ValueError(
                    "{0} is delayed and cannot be a causal-fit endpoint".format(
                        field
                    )
                )

        # Materialize the canonical event objects at the fit boundary.  The
        # flat record fields remain the wire/report format, but they cannot
        # bypass the identity and delayed-observation contract.
        event_specs = (
            (
                self.pc_tx_event_id,
                EVENT_PC_Q_SENT,
                CLOCK_DOMAIN_PC_MONOTONIC_NS,
                self.pc_tx_ns,
                self.pc_tx_event_observed_ns,
                self.pc_tx_event_data_age_ns,
                self.pc_tx_event_validity,
                self.pc_tx_event_uncertainty_ns,
                None,
                "PC",
            ),
            (
                self.q_event_id,
                EVENT_Q_UART_RX_ISR,
                CLOCK_DOMAIN_MCU_MONOTONIC_MS,
                self.q_event_tick_ms,
                self.q_event_observed_tick_ms,
                self.q_event_data_age_ms,
                self.q_event_validity,
                self.q_event_uncertainty_ns,
                self.pc_tx_event_id,
                "STM32_UART1",
            ),
            (
                self.q_parse_event_id,
                EVENT_Q_PARSE_DONE,
                CLOCK_DOMAIN_MCU_MONOTONIC_MS,
                self.q_parse_done_tick_ms,
                self.q_parse_event_observed_tick_ms,
                self.q_parse_event_data_age_ms,
                self.q_parse_event_validity,
                self.q_parse_event_uncertainty_ns,
                self.q_parse_causal_parent_event_id,
                "STM32_UART1",
            ),
            (
                self.t_event_id,
                EVENT_T_TRANSACTION_STARTED,
                CLOCK_DOMAIN_MCU_MONOTONIC_MS,
                self.t_event_tick_ms,
                self.t_event_observed_tick_ms,
                self.t_event_data_age_ms,
                self.t_event_validity,
                self.t_event_uncertainty_ns,
                self.q_parse_event_id,
                "STM32_ESP01S",
            ),
            (
                self.t_payload_event_id,
                EVENT_T_PAYLOAD_GENERATED,
                CLOCK_DOMAIN_MCU_MONOTONIC_MS,
                self.t_payload_generated_tick_ms,
                self.t_payload_event_observed_tick_ms,
                self.t_payload_event_data_age_ms,
                self.t_payload_event_validity,
                self.t_payload_event_uncertainty_ns,
                self.t_payload_causal_parent_event_id,
                "STM32_ESP01S",
            ),
            (
                self.pc_rx_event_id,
                EVENT_PC_T_RECEIVED,
                CLOCK_DOMAIN_PC_MONOTONIC_NS,
                self.pc_rx_ns,
                self.pc_rx_event_observed_ns,
                self.pc_rx_event_data_age_ns,
                self.pc_rx_event_validity,
                self.pc_rx_event_uncertainty_ns,
                self.t_payload_event_id,
                "PC",
            ),
        )
        for (
            event_id,
            event_kind,
            clock_domain,
            event_time,
            observed_time,
            data_age,
            validity,
            uncertainty,
            causal_parent_id,
            source_id,
        ) in event_specs:
            ClockEvent(
                event_id=event_id,
                sequence=self.sequence,
                source_id=source_id,
                event_kind=event_kind,
                clock_domain=clock_domain,
                event_time=event_time,
                observed_time=observed_time,
                data_age=data_age,
                validity=validity,
                uncertainty=uncertainty,
                causal_parent_id=causal_parent_id,
                transport="tcp",
                capture_id=self.capture_id,
            )

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> "ClockExchangeSample":
        if not isinstance(record, Mapping):
            raise ValueError("exchange record must be a mapping")
        missing = [field for field in _EXCHANGE_FIELDS if field not in record]
        if missing:
            causal_parent_fields = [
                field for field in missing
                if field.endswith("causal_parent_event_id")
            ]
            if causal_parent_fields:
                raise ValueError(
                    "missing causal parent identity field: {0}".format(
                        ", ".join(causal_parent_fields)
                    )
                )
            identity_fields = [
                field for field in missing
                if field == "observation_id" or field.endswith("_event_id")
            ]
            if identity_fields:
                raise ValueError(
                    "missing event identity field: {0}".format(
                        ", ".join(identity_fields)
                    )
                )
            raise ValueError(
                "missing exchange field: {0}".format(", ".join(missing))
            )
        required_integer_fields = (
                "sequence",
                "pc_tx_ns",
                "q_event_tick_ms",
                "t_event_tick_ms",
                "pc_rx_ns",
                "pc_tx_event_uncertainty_ns",
                "pc_tx_event_observed_ns",
                "pc_tx_event_data_age_ns",
                "q_event_observed_tick_ms",
                "q_event_data_age_ms",
                "q_event_uncertainty_ns",
                "t_event_observed_tick_ms",
                "t_event_data_age_ms",
                "t_event_uncertainty_ns",
                "pc_rx_event_uncertainty_ns",
                 "pc_rx_event_observed_ns",
                 "pc_rx_event_data_age_ns",
                 "timestamp_schema_version",
                 "q_parse_done_tick_ms",
                 "t_payload_generated_tick_ms",
        )
        optional_integer_fields = (
             "q_parse_event_observed_tick_ms",
             "q_parse_event_data_age_ms",
             "q_parse_event_uncertainty_ns",
             "t_payload_event_observed_tick_ms",
             "t_payload_event_data_age_ms",
             "t_payload_event_uncertainty_ns",
        )
        values = {
            field: _required_int(record, field)
            for field in required_integer_fields
        }
        values.update({
            field: _optional_int(record, field)
            for field in optional_integer_fields
        })
        capture_id = _required_text(record, "capture_id")
        values["capture_id"] = capture_id
        identity = ClockExchangeIdentity(
            transport="tcp", sequence=values["sequence"], capture_id=capture_id
        )
        expected_ids = {
            "observation_id": identity.exchange_id,
            "pc_tx_event_id": identity.event(EVENT_PC_Q_SENT),
            "q_event_id": identity.event(EVENT_Q_UART_RX_ISR),
            "q_parse_event_id": identity.event(EVENT_Q_PARSE_DONE),
            "t_event_id": identity.event(EVENT_T_TRANSACTION_STARTED),
            "t_payload_event_id": identity.event(EVENT_T_PAYLOAD_GENERATED),
            "pc_rx_event_id": identity.event(EVENT_PC_T_RECEIVED),
        }
        for field, expected in expected_ids.items():
            actual = _required_text(record, field)
            if actual != expected:
                raise ValueError(
                    "event identity {0} does not match its named boundary".format(
                        field
                    )
                )
        expected_causal_parents = {
            "q_parse_causal_parent_event_id": identity.event(EVENT_Q_UART_RX_ISR),
            "t_payload_causal_parent_event_id": identity.event(
                EVENT_T_TRANSACTION_STARTED
            ),
        }
        for field, expected in expected_causal_parents.items():
            actual = _required_text(record, field)
            if actual != expected:
                raise ValueError(
                    "{0} does not identify the expected causal parent".format(
                        field
                    )
                )
        expected_text = {
            "pc_tx_event_kind": EVENT_PC_Q_SENT,
            "pc_tx_event_clock_domain": CLOCK_DOMAIN_PC_MONOTONIC_NS,
            "pc_tx_event_validity": OBSERVED_BOUNDARY,
            "q_event_kind": EVENT_Q_UART_RX_ISR,
            "q_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
            "q_event_validity": OBSERVED_BOUNDARY,
            "q_parse_event_kind": EVENT_Q_PARSE_DONE,
            "q_parse_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
            "q_parse_event_validity": REPORTED_BOUNDARY,
            "t_event_kind": EVENT_T_TRANSACTION_STARTED,
            "t_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
            "t_event_validity": OBSERVED_BOUNDARY,
            "t_payload_event_kind": EVENT_T_PAYLOAD_GENERATED,
            "t_payload_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
            "t_payload_event_validity": REPORTED_BOUNDARY,
            "pc_rx_event_kind": EVENT_PC_T_RECEIVED,
            "pc_rx_event_clock_domain": CLOCK_DOMAIN_PC_MONOTONIC_NS,
            "pc_rx_event_validity": OBSERVED_BOUNDARY,
            "q_parse_role": "diagnostic_only",
            "t_payload_role": "diagnostic_only",
        }
        for field, expected in expected_text.items():
            if _required_text(record, field) != expected:
                raise ValueError(
                    "exchange event metadata {0} is not fit-eligible".format(field)
                )
        return cls(
            **values,
            pc_tx_event_kind=expected_text["pc_tx_event_kind"],
            pc_tx_event_clock_domain=expected_text["pc_tx_event_clock_domain"],
            pc_tx_event_validity=expected_text["pc_tx_event_validity"],
            q_event_kind=expected_text["q_event_kind"],
            t_event_kind=expected_text["t_event_kind"],
            pc_rx_event_kind=expected_text["pc_rx_event_kind"],
            pc_rx_event_clock_domain=expected_text["pc_rx_event_clock_domain"],
            pc_rx_event_validity=expected_text["pc_rx_event_validity"],
            q_parse_event_kind=expected_text["q_parse_event_kind"],
            q_parse_event_clock_domain=expected_text[
                "q_parse_event_clock_domain"
            ],
            q_parse_event_validity=expected_text["q_parse_event_validity"],
            q_parse_causal_parent_event_id=expected_causal_parents[
                "q_parse_causal_parent_event_id"
            ],
            q_parse_role=expected_text["q_parse_role"],
            t_payload_event_kind=expected_text["t_payload_event_kind"],
            t_payload_event_clock_domain=expected_text[
                "t_payload_event_clock_domain"
            ],
            t_payload_event_validity=expected_text[
                "t_payload_event_validity"
            ],
            t_payload_causal_parent_event_id=expected_causal_parents[
                "t_payload_causal_parent_event_id"
            ],
            t_payload_role=expected_text["t_payload_role"],
        )

    @property
    def observation_id(self) -> str:
        return ClockExchangeIdentity(
            transport="tcp", sequence=self.sequence, capture_id=self.capture_id
        ).exchange_id

    def _event_id(self, event_kind: str) -> str:
        return ClockExchangeIdentity(
            transport="tcp", sequence=self.sequence, capture_id=self.capture_id
        ).event(event_kind)

    @property
    def pc_tx_event_id(self) -> str:
        return self._event_id(EVENT_PC_Q_SENT)

    @property
    def q_event_id(self) -> str:
        return self._event_id(EVENT_Q_UART_RX_ISR)

    @property
    def q_parse_event_id(self) -> str:
        return self._event_id(EVENT_Q_PARSE_DONE)

    @property
    def t_event_id(self) -> str:
        return self._event_id(EVENT_T_TRANSACTION_STARTED)

    @property
    def t_payload_event_id(self) -> str:
        return self._event_id(EVENT_T_PAYLOAD_GENERATED)

    @property
    def pc_rx_event_id(self) -> str:
        return self._event_id(EVENT_PC_T_RECEIVED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capture_id": self.capture_id,
            "observation_id": self.observation_id,
            "sequence": self.sequence,
            "pc_tx_ns": self.pc_tx_ns,
            "pc_tx_event_id": self.pc_tx_event_id,
            "pc_tx_event_kind": self.pc_tx_event_kind,
            "pc_tx_event_clock_domain": self.pc_tx_event_clock_domain,
            "pc_tx_event_validity": self.pc_tx_event_validity,
            "pc_tx_event_uncertainty_ns": self.pc_tx_event_uncertainty_ns,
            "pc_tx_event_observed_ns": self.pc_tx_event_observed_ns,
            "pc_tx_event_data_age_ns": self.pc_tx_event_data_age_ns,
            "q_event_id": self.q_event_id,
            "q_event_tick_ms": self.q_event_tick_ms,
            "q_event_observed_tick_ms": self.q_event_observed_tick_ms,
            "q_event_data_age_ms": self.q_event_data_age_ms,
            "q_event_kind": self.q_event_kind,
            "q_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
            "q_event_validity": self.q_event_validity,
            "q_event_uncertainty_ns": self.q_event_uncertainty_ns,
            "q_parse_event_id": self.q_parse_event_id,
            "q_parse_causal_parent_event_id": self.q_parse_causal_parent_event_id,
            "q_parse_done_tick_ms": self.q_parse_done_tick_ms,
            "q_parse_event_kind": self.q_parse_event_kind,
            "q_parse_event_clock_domain": self.q_parse_event_clock_domain,
            "q_parse_event_validity": self.q_parse_event_validity,
            "q_parse_event_uncertainty_ns": self.q_parse_event_uncertainty_ns,
            "q_parse_event_observed_tick_ms": self.q_parse_event_observed_tick_ms,
            "q_parse_event_data_age_ms": self.q_parse_event_data_age_ms,
            "q_parse_role": self.q_parse_role,
            "t_event_id": self.t_event_id,
            "t_event_tick_ms": self.t_event_tick_ms,
            "t_event_observed_tick_ms": self.t_event_observed_tick_ms,
            "t_event_data_age_ms": self.t_event_data_age_ms,
            "t_event_kind": self.t_event_kind,
            "t_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
            "t_event_validity": self.t_event_validity,
            "t_event_uncertainty_ns": self.t_event_uncertainty_ns,
            "t_payload_event_id": self.t_payload_event_id,
            "t_payload_causal_parent_event_id": (
                self.t_payload_causal_parent_event_id
            ),
            "t_payload_generated_tick_ms": self.t_payload_generated_tick_ms,
            "t_payload_event_kind": self.t_payload_event_kind,
            "t_payload_event_clock_domain": self.t_payload_event_clock_domain,
            "t_payload_event_validity": self.t_payload_event_validity,
            "t_payload_event_uncertainty_ns": self.t_payload_event_uncertainty_ns,
            "t_payload_event_observed_tick_ms": self.t_payload_event_observed_tick_ms,
            "t_payload_event_data_age_ms": self.t_payload_event_data_age_ms,
            "t_payload_role": self.t_payload_role,
            "pc_rx_ns": self.pc_rx_ns,
            "pc_rx_event_id": self.pc_rx_event_id,
            "pc_rx_event_kind": self.pc_rx_event_kind,
            "pc_rx_event_clock_domain": self.pc_rx_event_clock_domain,
            "pc_rx_event_validity": self.pc_rx_event_validity,
            "pc_rx_event_uncertainty_ns": self.pc_rx_event_uncertainty_ns,
            "pc_rx_event_observed_ns": self.pc_rx_event_observed_ns,
            "pc_rx_event_data_age_ns": self.pc_rx_event_data_age_ns,
            "timestamp_schema_version": self.timestamp_schema_version,
        }


@dataclass(frozen=True)
class CausalSyncPolicy:
    """Explicit thresholds for the physical-event synchronization gate."""

    min_exchanges: int = 8
    max_rtt_p95_ns: int = 20_000_000
    max_residual_p95_ns: int = 5_000_000
    max_uncertainty_p95_ns: int = 10_000_000

    def __post_init__(self) -> None:
        values = {
            "min_exchanges": self.min_exchanges,
            "max_rtt_p95_ns": self.max_rtt_p95_ns,
            "max_residual_p95_ns": self.max_residual_p95_ns,
            "max_uncertainty_p95_ns": self.max_uncertainty_p95_ns,
        }
        for field, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("{0} must be an integer".format(field))
            if value < 0:
                raise ValueError("{0} must be non-negative".format(field))
        if self.min_exchanges < 2:
            raise ValueError("min_exchanges must be at least 2")


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), percentile))


@dataclass(frozen=True)
class CausalClockFit:
    """Linear mapping fitted from four-timestamp clock exchanges."""

    samples: Tuple[ClockExchangeSample, ...]
    slope_ns_per_ms: float
    offset_ns: float
    rtt_ns: Tuple[float, ...]
    residual_ns: Tuple[float, ...]
    uncertainty_ns: Tuple[float, ...]

    @classmethod
    def fit(cls, samples: Sequence[ClockExchangeSample]) -> "CausalClockFit":
        normalized = tuple(samples)
        if len(normalized) < 2:
            raise ValueError("at least 2 clock exchange samples are required")
        if any(not isinstance(sample, ClockExchangeSample)
               for sample in normalized):
            raise ValueError("samples must contain ClockExchangeSample values")
        for previous, current in zip(normalized, normalized[1:]):
            if current.sequence <= previous.sequence:
                raise ValueError("exchange sequence must be strictly increasing")

        midpoint_ticks = []
        midpoint_pc_ns = []
        rtt_ns = []
        for sample in normalized:
            round_trip_ns = (
                sample.pc_rx_ns - sample.pc_tx_ns
                - (sample.t_event_tick_ms - sample.q_event_tick_ms) * 1_000_000
            )
            if round_trip_ns < 0:
                raise ValueError(
                    "clock exchange has negative transport round-trip time"
                )
            midpoint_ticks.append(
                (sample.q_event_tick_ms + sample.t_event_tick_ms) / 2.0
            )
            midpoint_pc_ns.append((sample.pc_tx_ns + sample.pc_rx_ns) / 2.0)
            rtt_ns.append(float(round_trip_ns))

        x = np.asarray(midpoint_ticks, dtype=float)
        y = np.asarray(midpoint_pc_ns, dtype=float)
        count = float(len(x))
        sum_x = float(x.sum())
        sum_y = float(y.sum())
        sum_xx = float((x * x).sum())
        sum_xy = float((x * y).sum())
        denominator = count * sum_xx - sum_x * sum_x
        if abs(denominator) < 1e-12:
            raise ValueError("clock exchange ticks are degenerate")
        slope = (count * sum_xy - sum_x * sum_y) / denominator
        offset = (sum_y - slope * sum_x) / count
        if not np.isfinite(slope) or not np.isfinite(offset):
            raise ValueError("clock fit is not finite")

        residuals = tuple(
            float(abs(slope * tick + offset - pc_ns))
            for tick, pc_ns in zip(midpoint_ticks, midpoint_pc_ns)
        )
        uncertainty = tuple(
            float(
                delay / 2.0
                + sample.pc_tx_event_uncertainty_ns
                + sample.q_event_uncertainty_ns
                + sample.t_event_uncertainty_ns
                + sample.pc_rx_event_uncertainty_ns
                + 0.5 * abs(slope)
            )
            for delay, sample in zip(rtt_ns, normalized)
        )
        return cls(
            samples=normalized,
            slope_ns_per_ms=float(slope),
            offset_ns=float(offset),
            rtt_ns=tuple(rtt_ns),
            residual_ns=residuals,
            uncertainty_ns=uncertainty,
        )

    def tick_to_pc_ns(self, tick_ms: float) -> float:
        """Map an MCU monotonic tick to the host monotonic time domain."""
        value = self.slope_ns_per_ms * float(tick_ms) + self.offset_ns
        if not np.isfinite(value):
            raise ValueError("mapped PC timestamp is not finite")
        return float(value)

    def metrics(self) -> Dict[str, float | int]:
        residuals = self.residual_ns
        rtt = self.rtt_ns
        uncertainty = self.uncertainty_ns
        residual_array = np.asarray(residuals, dtype=float)
        return {
            "sample_count": len(self.samples),
            "slope_ns_per_ms": self.slope_ns_per_ms,
            "offset_ns": self.offset_ns,
            "drift_ppm": (self.slope_ns_per_ms / 1_000_000.0 - 1.0) * 1_000_000.0,
            "rtt_min_ns": float(min(rtt)),
            "rtt_median_ns": float(np.median(np.asarray(rtt, dtype=float))),
            "rtt_p95_ns": _percentile(rtt, 95.0),
            "rtt_max_ns": float(max(rtt)),
            "residual_rms_ns": float(np.sqrt(np.mean(residual_array ** 2))),
            "residual_p95_ns": _percentile(residuals, 95.0),
            "residual_max_ns": float(max(residuals)),
            "uncertainty_p95_ns": _percentile(uncertainty, 95.0),
            "uncertainty_max_ns": float(max(uncertainty)),
        }


@dataclass(frozen=True)
class CausalSyncGateResult:
    """Independent verdict for causal clock synchronization."""

    verdict: str
    metrics: Dict[str, float | int]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            **dict(self.metrics),
        }


def evaluate_causal_sync(
    fit: CausalClockFit,
    policy: CausalSyncPolicy,
) -> CausalSyncGateResult:
    """Evaluate measured exchange quality without hiding failed samples."""
    metrics = fit.metrics()
    if int(metrics["sample_count"]) < policy.min_exchanges:
        return CausalSyncGateResult(
            verdict="INSUFFICIENT EVIDENCE",
            metrics=metrics,
            reason=(
                "too few clock exchanges: {0} < {1}"
                .format(metrics["sample_count"], policy.min_exchanges)
            ),
        )

    failures = []
    if metrics["rtt_p95_ns"] > policy.max_rtt_p95_ns:
        failures.append("rtt_p95_ns exceeds policy")
    if metrics["residual_p95_ns"] > policy.max_residual_p95_ns:
        failures.append("residual_p95_ns exceeds policy")
    if metrics["uncertainty_p95_ns"] > policy.max_uncertainty_p95_ns:
        failures.append("uncertainty_p95_ns exceeds policy")
    if failures:
        return CausalSyncGateResult(
            verdict="FAIL",
            metrics=metrics,
            reason="; ".join(failures),
        )
    return CausalSyncGateResult(
        verdict="PASS",
        metrics=metrics,
        reason="exchange count and causal clock quality thresholds pass",
    )


def _policy_dict(policy: CausalSyncPolicy) -> Dict[str, int]:
    return {
        "min_exchanges": policy.min_exchanges,
        "max_rtt_p95_ns": policy.max_rtt_p95_ns,
        "max_residual_p95_ns": policy.max_residual_p95_ns,
        "max_uncertainty_p95_ns": policy.max_uncertainty_p95_ns,
    }


def _fail_closed_report(
    reason: str,
    policy: CausalSyncPolicy,
    *,
    record_count: int,
    excluded_record_count: int = 0,
    unclassified_record_count: int = 0,
) -> Dict[str, Any]:
    return {
        "verdict": "INSUFFICIENT EVIDENCE",
        "reason": reason,
        "record_count": int(record_count),
        "excluded_record_count": int(excluded_record_count),
        "unclassified_record_count": int(unclassified_record_count),
        "sample_count": 0,
        "fit": None,
        "exchange_fields": list(_EXCHANGE_FIELDS),
        "policy": _policy_dict(policy),
    }


def build_causal_sync_report(
    exchange_records: Sequence[Mapping[str, Any]],
    policy: CausalSyncPolicy = None,
) -> Dict[str, Any]:
    """Build a fail-closed JSON-compatible causal-sync report."""
    selected_policy = policy or CausalSyncPolicy()
    records = list(exchange_records)
    fit_records = []
    excluded_record_count = 0
    unclassified_record_count = 0
    try:
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError("clock exchange record must be a mapping")
            if any(field not in record for field in _EXCHANGE_FIELDS):
                # A legacy or partially classified record cannot be fitted.
                unclassified_record_count += 1
                continue
            if (
                "sample_role" not in record
                or "included_in_fit" not in record
            ):
                unclassified_record_count += 1
                continue
            sample_role = record["sample_role"]
            if sample_role not in {"arm_probe", "formal"}:
                raise ValueError(
                    "sample_role must be 'arm_probe' or 'formal'"
                )
            included_in_fit = record["included_in_fit"]
            if not isinstance(included_in_fit, bool):
                raise ValueError("included_in_fit must be boolean")
            expected_inclusion = sample_role == "formal"
            explicit_evidence_exclusion = (
                not included_in_fit
                and sample_role == "formal"
                and isinstance(record.get("fit_exclusion_reason"), str)
                and bool(record["fit_exclusion_reason"])
            )
            if included_in_fit != expected_inclusion and not explicit_evidence_exclusion:
                raise ValueError(
                    "sample_role and included_in_fit are inconsistent"
                )
            if included_in_fit:
                fit_records.append(record)
            else:
                excluded_record_count += 1
    except (TypeError, ValueError) as error:
        return _fail_closed_report(
            "invalid clock exchange evidence: {0}".format(error),
            selected_policy,
            record_count=len(records),
            excluded_record_count=excluded_record_count,
            unclassified_record_count=unclassified_record_count,
        )
    if not records:
        return _fail_closed_report(
            "no clock exchange samples recorded",
            selected_policy,
            record_count=0,
        )
    if unclassified_record_count:
        return _fail_closed_report(
            "clock exchange records lack explicit sample-role classification",
            selected_policy,
            record_count=len(records),
            excluded_record_count=excluded_record_count,
            unclassified_record_count=unclassified_record_count,
        )
    if not fit_records:
        uncertainty_unverified = bool(records) and all(
            record.get("fit_exclusion_reason") == "uncertainty_unverified"
            for record in records
            if not record.get("included_in_fit")
        )
        reason = (
            "no clock exchange samples have an independently verified "
            "uncertainty bound"
            if uncertainty_unverified
            else "no clock exchange samples included in causal fit"
        )
        return _fail_closed_report(
            reason,
            selected_policy,
            record_count=len(records),
            excluded_record_count=excluded_record_count,
        )
    try:
        samples = tuple(
            ClockExchangeSample.from_dict(record) for record in fit_records
        )
        fit = CausalClockFit.fit(samples)
    except (TypeError, ValueError) as error:
        return _fail_closed_report(
            "invalid clock exchange evidence: {0}".format(error),
            selected_policy,
            record_count=len(records),
            excluded_record_count=excluded_record_count,
        )

    result = evaluate_causal_sync(fit, selected_policy).to_dict()
    result["record_count"] = len(records)
    result["excluded_record_count"] = excluded_record_count
    result["fit"] = "midpoint_linear"
    result["exchange_fields"] = list(_EXCHANGE_FIELDS)
    result["policy"] = _policy_dict(selected_policy)
    return result


__all__ = [
    "CausalClockFit",
    "CausalSyncGateResult",
    "CausalSyncPolicy",
    "ClockExchangeSample",
    "build_causal_sync_report",
    "evaluate_causal_sync",
]
