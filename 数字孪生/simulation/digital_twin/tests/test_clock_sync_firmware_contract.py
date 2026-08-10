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
    assert "esp_transport_peek_pending_clock_sync" in main
    assert "esp_transport_consume_pending_clock_sync" in main
    assert "CIPSEND_TX_TAG_TELEMETRY" in main
    assert "twin_control_encode_clock_sync" in protocol

    clock_block_start = main.index("/* --- Clock sync response")
    clock_block_end = main.index("/* --- Telemetry", clock_block_start)
    clock_block = main[clock_block_start:clock_block_end]
    assert "CIPSEND_TX_TAG_CLOCK_SYNC" in clock_block
    assert "CIPSEND_TX_TAG_TELEMETRY" not in clock_block


def test_clock_response_does_not_change_existing_telemetry_frame_size():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    assert "uint8_t len  = 26;" in main
    assert "TELEMETRY_BATCH_FRAME_SIZE" in main


def test_clock_response_timestamp_is_filled_at_payload_ready_boundary():
    tx_header = (FIRMWARE / "cipsend_tx.h").read_text(encoding="utf-8")
    tx_source = (FIRMWARE / "cipsend_tx.c").read_text(encoding="utf-8")
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    assert "cipsend_tx_start_late_data" in tx_header
    assert "data_ready" in tx_source
    assert "cipsend_tx_start_late_data" in main
    assert "twin_control_encode_clock_sync_fixed" in main


def test_clock_sync_pending_is_consumed_only_after_send_ok():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    clock_block_start = main.index("/* --- Clock sync response")
    clock_block_end = main.index("/* --- Telemetry", clock_block_start)
    clock_block = main[clock_block_start:clock_block_end]
    terminal_block_start = main.index("static void ESP_TX_HandleTerminal")
    terminal_block_end = main.index("/* Phase 1:", terminal_block_start)
    terminal_block = main[terminal_block_start:terminal_block_end]

    assert "esp_transport_consume_pending_clock_sync" not in clock_block
    assert "terminal_tag == CIPSEND_TX_TAG_CLOCK_SYNC" in terminal_block
    assert "terminal_result == CTS_RESULT_OK" in terminal_block
    assert "esp_transport_consume_pending_clock_sync" in terminal_block


def test_clock_sync_has_a_transaction_tag_distinct_from_legacy_diag():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    clock_block_start = main.index("/* --- Clock sync response")
    clock_block_end = main.index("/* --- Telemetry", clock_block_start)
    clock_block = main[clock_block_start:clock_block_end]
    terminal_block_start = main.index("static void ESP_TX_HandleTerminal")
    terminal_block_end = main.index("/* Phase 1:", terminal_block_start)
    terminal_block = main[terminal_block_start:terminal_block_end]
    diag_block_start = main.index("static uint8_t ESP_SendDiagFrame")
    diag_block_end = main.index("/* 发送队列", diag_block_start)
    diag_block = main[diag_block_start:diag_block_end]

    assert "CIPSEND_TX_TAG_CLOCK_SYNC" in clock_block
    assert "CIPSEND_TX_TAG_DIAG" not in clock_block
    assert "terminal_tag == CIPSEND_TX_TAG_CLOCK_SYNC" in terminal_block
    assert "tag = CIPSEND_TX_TAG_DIAG" in diag_block
