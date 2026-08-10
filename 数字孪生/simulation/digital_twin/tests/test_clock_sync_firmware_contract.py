"""Fail-closed source contract for the Q -> T firmware integration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIRMWARE = ROOT / "firmware" / "stm32_line_follower" / "User"


def test_clock_probe_uses_existing_protocol_and_transport_path():
    protocol = (FIRMWARE / "twin_control_protocol.c").read_text(encoding="utf-8")
    transport = (FIRMWARE / "esp_runtime_transport.c").read_text(encoding="utf-8")
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    assert 'strcmp(fields[0], "Q")' in protocol
    assert "twin_control_receive_byte_at" in transport
    assert "esp_transport_get_pending_clock_sync" in main
    assert "CIPSEND_TX_TAG_TELEMETRY" in main
    assert "twin_control_encode_clock_sync" in protocol

    clock_block_start = main.index("/* --- Clock sync response")
    clock_block_end = main.index("/* --- Telemetry", clock_block_start)
    clock_block = main[clock_block_start:clock_block_end]
    assert "CIPSEND_TX_TAG_DIAG" in clock_block
    assert "CIPSEND_TX_TAG_TELEMETRY" not in clock_block


def test_clock_response_does_not_change_existing_telemetry_frame_size():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    assert "uint8_t len  = 26;" in main
    assert "TELEMETRY_BATCH_FRAME_SIZE" in main
