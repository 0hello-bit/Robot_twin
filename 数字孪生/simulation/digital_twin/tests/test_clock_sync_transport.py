"""Offline contract tests for the isolated TCP/UDP ClockSync comparison."""

from __future__ import annotations

import pytest

from v1_twin.clock_sync_transport import (
    ClockSyncTransportContractError,
    ClockSyncTransportObservation,
    ClockSyncTransportProfile,
    EspUdpCapabilityEvidence,
    summarize_clock_sync_transport,
)


def test_tcp_and_udp_profiles_share_non_transport_contract():
    tcp = ClockSyncTransportProfile("tcp")
    udp = ClockSyncTransportProfile("udp")

    tcp.validate()
    udp.validate()

    tcp_dict = tcp.to_dict()
    udp_dict = udp.to_dict()
    assert tcp_dict["transport"] == "tcp"
    assert udp_dict["transport"] == "udp"
    for key in tcp_dict:
        if key != "transport":
            assert tcp_dict[key] == udp_dict[key]


def test_udp_without_at_capability_evidence_is_insufficient():
    result = ClockSyncTransportProfile("udp").readiness()

    assert result["verdict"] == "INSUFFICIENT EVIDENCE"
    assert result["missing"]


def test_udp_requires_complete_capability_evidence():
    evidence = EspUdpCapabilityEvidence(
        at_gmr="AT version: captured",
        cipmux=1,
        cipmode=0,
        udp_supported=True,
        ipd_header_mode="link_id_length",
        udp_capability_source="documented_command_matrix",
    )

    result = ClockSyncTransportProfile("udp").readiness(evidence)

    assert result["verdict"] == "READY"
    assert result["missing"] == []


def test_four_at_queries_do_not_infer_udp_support_without_capability_source():
    evidence = EspUdpCapabilityEvidence(
        at_gmr="AT version: captured",
        cipmux=1,
        cipmode=0,
        udp_supported=True,
        ipd_header_mode="link_id_length",
    )

    result = ClockSyncTransportProfile("udp").readiness(evidence)

    assert result["verdict"] == "INSUFFICIENT EVIDENCE"
    assert "udp_capability_source" in result["missing"]


@pytest.mark.parametrize("source", [None, "", "   ", 1])
def test_udp_capability_source_must_be_explicit_text(source):
    evidence = EspUdpCapabilityEvidence(
        at_gmr="AT version: captured",
        cipmux=1,
        cipmode=0,
        udp_supported=True,
        ipd_header_mode="link_id_length",
        udp_capability_source=source,
    )

    result = ClockSyncTransportProfile("udp").readiness(evidence)

    assert result["verdict"] == "INSUFFICIENT EVIDENCE"
    assert "udp_capability_source" in result["missing"]


def test_udp_rejects_non_response_at_gmr_text():
    evidence = EspUdpCapabilityEvidence(
        at_gmr="arbitrary text",
        cipmux=1,
        cipmode=0,
        udp_supported=True,
        ipd_header_mode="link_id_length",
        udp_capability_source="documented_command_matrix",
    )

    result = ClockSyncTransportProfile("udp").readiness(evidence)

    assert result["verdict"] == "INSUFFICIENT EVIDENCE"
    assert "at_gmr" in result["missing"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cipmux", True),
        ("cipmux", 1.0),
        ("cipmode", False),
        ("cipmode", 0.0),
    ],
)
def test_udp_rejects_non_integer_cip_configuration(field, value):
    values = {
        "at_gmr": "AT version: captured",
        "cipmux": 1,
        "cipmode": 0,
        "udp_supported": True,
        "ipd_header_mode": "link_id_length",
        "udp_capability_source": "documented_command_matrix",
    }
    values[field] = value

    result = ClockSyncTransportProfile("udp").readiness(
        EspUdpCapabilityEvidence(**values)
    )

    assert result["verdict"] == "INSUFFICIENT EVIDENCE"


@pytest.mark.parametrize("transport", [[], None, "serial"])
def test_profile_rejects_invalid_transport(transport):
    with pytest.raises(ClockSyncTransportContractError):
        ClockSyncTransportProfile(transport).validate()


@pytest.mark.parametrize("field", [
    "telemetry_migrated",
    "health_migrated",
    "control_migrated",
])
def test_profile_rejects_stream_migration(field):
    values = {field: True}

    with pytest.raises(ClockSyncTransportContractError):
        ClockSyncTransportProfile("udp", **values).validate()


def _matched(sequence, total_rtt_ns, transport_rtt_ns,
             duplicate_count=0, reordered=False):
    return ClockSyncTransportObservation(
        sequence=sequence,
        pc_tx_ns=sequence * 1_000_000_000,
        pc_rx_ns=sequence * 1_000_000_000 + total_rtt_ns,
        matched=True,
        rtt_transport_ns=transport_rtt_ns,
        duplicate_count=duplicate_count,
        reordered=reordered,
    )


def test_summary_preserves_loss_duplicates_reorder_and_high_rtt():
    observations = [
        _matched(1, 10_000_000, 5_000_000),
        _matched(2, 20_000_000, 10_000_000),
        _matched(3, 1_000_000_000, 900_000_000,
                 duplicate_count=1, reordered=True),
        ClockSyncTransportObservation(
            sequence=4,
            pc_tx_ns=4_000_000_000,
            matched=False,
        ),
        ClockSyncTransportObservation(
            sequence=5,
            pc_tx_ns=5_000_000_000,
            pc_rx_ns=6_000_000_000,
            matched=False,
            late_reply=True,
        ),
    ]

    summary = summarize_clock_sync_transport(observations)

    assert summary["sent_count"] == 5
    assert summary["matched_count"] == 3
    assert summary["lost_count"] == 2
    assert summary["duplicate_count"] == 1
    assert summary["reordered_count"] == 1
    assert summary["late_reply_count"] == 1
    assert summary["total_rtt_max_ns"] == 1_000_000_000
    assert summary["total_rtt_p95_ns"] > 20_000_000


def test_observation_rejects_matched_without_receive_timestamp():
    with pytest.raises(ClockSyncTransportContractError, match="pc_rx_ns"):
        ClockSyncTransportObservation(
            sequence=1,
            pc_tx_ns=100,
            matched=True,
        )


def test_observation_rejects_wrong_pc_clock_source():
    with pytest.raises(ClockSyncTransportContractError, match="pc_clock_source"):
        ClockSyncTransportObservation(
            sequence=1,
            pc_tx_ns=100,
            pc_rx_ns=200,
            matched=True,
            pc_clock_source="monotonic_ns",
        )


def test_summary_rejects_duplicate_sequence_records():
    observation = _matched(1, 10_000_000, 5_000_000)

    with pytest.raises(ClockSyncTransportContractError, match="sequence"):
        summarize_clock_sync_transport([observation, observation])
