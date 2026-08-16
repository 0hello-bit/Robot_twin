"""Fail-closed source contract for the Q -> T firmware integration."""

import re
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


def test_telemetry_timestamp_is_captured_at_generation_boundary():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    queue_start = main.index("static void Telemetry_Queue")
    queue_end = main.index("static uint8_t ESP_SendDiagFrame", queue_start)
    queue_block = main[queue_start:queue_end]

    timestamp_line = "generation_tick_ms = mono_now_ms();"
    assert "uint32_t tick" not in queue_block
    assert timestamp_line in queue_block
    assert queue_block.index(timestamp_line) < queue_block.index(
        "build_telemetry_frame("
    )
    assert re.search(
        r"build_telemetry_frame\([\s\S]*?generation_tick_ms",
        queue_block,
    )

    call_arguments = re.findall(
        r"Telemetry_Queue\(([\s\S]*?)\);", main[queue_end:]
    )
    assert len(call_arguments) == 3
    assert all("s_last_telemetry_ms" not in call for call in call_arguments)


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


def test_timing_diagnostic_captures_each_stage_and_send_terminal():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")
    batch = (FIRMWARE / "telemetry_batch.h").read_text(encoding="utf-8")
    delivery = (FIRMWARE / "telemetry_delivery.h").read_text(encoding="utf-8")
    timing = (FIRMWARE / "timing_diagnostic.h").read_text(encoding="utf-8")

    for field in (
        "t_imu_start_ms", "t_imu_done_ms", "t_sensor_done_ms",
        "t_state_ms", "t_enqueue_ms", "t_tx_start_ms", "t_send_ok_ms",
    ):
        assert field in main
        assert field in batch or field in timing

    assert "TIMING_DIAGNOSTIC_TYPE" in timing
    assert "TIMING_DIAGNOSTIC_FRAME_SIZE" in timing
    assert "TelemetryTimingRecord" in batch
    assert "telemetry_delivery_append_timed" in delivery
    assert "telemetry_delivery_mark_inflight_tx_start" in delivery
    assert "ESP_TrySendTimingDiagnostic" in main
    assert "terminal_tag == CIPSEND_TX_TAG_TELEMETRY" in main
    assert "terminal_result == CTS_RESULT_OK" in main

    imu_start = main.index("t_imu_start_ms = mono_now_ms()")
    imu_read = main.index("MPU6050_ReadAll()")
    imu_done = main.index("t_imu_done_ms = mono_now_ms()")
    sensor_done = main.index("t_sensor_done_ms = mono_now_ms()")
    queue_start = main.index("static void Telemetry_Queue")
    enqueue = main.index(
        "telemetry_delivery_mark_last_pending_enqueue", queue_start
    )
    assert imu_start < imu_read < imu_done < sensor_done
    queue_block = main[queue_start:]
    assert "t_state_ms = generation_tick_ms" in queue_block[:enqueue]


def test_timing_diagnostic_does_not_change_existing_telemetry_frame_contract():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")
    assert "uint8_t len  = 26;" in main
    assert "TELEMETRY_BATCH_FRAME_SIZE 31U" in (
        FIRMWARE / "telemetry_batch.h"
    ).read_text(encoding="utf-8")


def test_pending_timing_diagnostic_precedes_droppable_telemetry():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")
    flush_start = main.index("static void ESP_FlushAfterControl")
    flush_end = main.index("int main(void)", flush_start)
    flush_block = main[flush_start:flush_end]

    assert flush_block.index("ESP_TrySendTimingDiagnostic();") < flush_block.index(
        "ESP_SendQueuedFrames(1U);"
    )


def test_timing_priority_fix_has_a_distinct_firmware_identity():
    health = (FIRMWARE / "health_frame.h").read_text(encoding="utf-8")
    assert "Build 5: timing-diagnostic CIPSEND priority repair" in health
    assert "#define FW_BUILD_ID 5U" in health


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


def test_clock_sync_event_arms_a_firmware_quiet_window():
    header = (FIRMWARE / "esp_runtime_transport.h").read_text(encoding="utf-8")
    transport = (FIRMWARE / "esp_runtime_transport.c").read_text(encoding="utf-8")
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    assert "esp_transport_take_clock_sync_event" in header
    assert "esp_transport_take_clock_sync_event" in transport
    assert "EspClockQuietWindow" in header
    assert "ESP_CLOCK_QUIET_WINDOW_MS" in header
    assert "esp_clock_quiet_arm" in header
    assert "esp_clock_quiet_active" in header
    assert "esp_clock_quiet_reset" in header
    assert "esp_transport_take_clock_sync_event" in main
    assert "esp_clock_quiet_arm" in main


def test_quiet_window_blocks_droppable_starts_without_consuming_health_due():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    telemetry_start = main.index("static void ESP_TrySendTelemetry")
    telemetry_end = main.index("/* 遥测入队", telemetry_start)
    telemetry_block = main[telemetry_start:telemetry_end]
    diag_start = main.index("static uint8_t ESP_SendDiagFrame")
    diag_end = main.index("static void ESP_TrySendImuDiagnostic", diag_start)
    diag_block = main[diag_start:diag_end]
    health_start = main.index("static void health_flush_pending")
    health_end = main.index("static void ESP_DrainPendingStatus", health_start)
    health_block = main[health_start:health_end]

    assert "esp_clock_quiet_active" in telemetry_block
    assert "esp_clock_quiet_active" in diag_block
    assert "esp_clock_quiet_active" in health_block
    quiet_guard = health_block.index("esp_clock_quiet_active")
    consume_due = health_block.index("hstats_health_consume_due")
    assert quiet_guard < consume_due


def test_quiet_window_is_cleared_at_connection_boundaries():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    disconnected_start = main.index("static void ESP_MarkDisconnected")
    disconnected_end = main.index("/* 终态处理", disconnected_start)
    disconnected_block = main[disconnected_start:disconnected_end]
    service_start = main.index("static void ESP_ServiceTX")
    service_end = main.index("/* 构建 31 字节遥测帧", service_start)
    service_block = main[service_start:service_end]

    assert "esp_clock_quiet_reset" in disconnected_block
    assert "esp_clock_quiet_reset" in service_block


def test_esp_capability_diagnostic_uses_existing_transport_and_cipsend():
    project = (FIRMWARE.parent / "project.uvprojx").read_text(encoding="utf-8")
    header = (FIRMWARE / "esp_runtime_transport.h").read_text(encoding="utf-8")
    transport = (FIRMWARE / "esp_runtime_transport.c").read_text(encoding="utf-8")
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    assert "esp_at_diagnostic.c" in project
    assert "esp_at_diagnostic.h" in project
    assert '#include "esp_at_diagnostic.h"' in transport
    for symbol in (
        "esp_at_diagnostic_feed_request_byte",
        "esp_at_diagnostic_feed_response_byte",
        "esp_at_diagnostic_command",
        "esp_at_diagnostic_mark_command_sent_at",
        "esp_at_diagnostic_peek_response",
        "esp_at_diagnostic_consume_response",
    ):
        assert symbol in transport
    assert "esp_transport_diagnostic_busy" in header
    assert "esp_transport_diagnostic_busy" in main
    assert "CIPSEND_TX_TAG_DIAG" in main
    assert "cipsend_tx_start(" in main
    assert "ESP_Send(esp" not in main
    assert "sprintf(cmd, \"AT+%" not in main
    assert "ESP_ServiceCapabilityDiagnostic" in main
    assert "uart_tx_sink" in main
    assert "esp_transport_diagnostic_command" in main
    assert "esp_transport_diagnostic_mark_command_sent" in main
    assert "esp_transport_diagnostic_response_ready" in main
    assert "esp_transport_diagnostic_consume_response" in main

    telemetry_start = main.index("static void ESP_TrySendTelemetry")
    telemetry_end = main.index("/* 遥测入队", telemetry_start)
    telemetry_block = main[telemetry_start:telemetry_end]
    assert "esp_transport_diagnostic_busy" in telemetry_block

    diag_start = main.index("static uint8_t ESP_SendDiagFrame")
    diag_end = main.index("static void ESP_TrySendImuDiagnostic", diag_start)
    diag_block = main[diag_start:diag_end]
    assert "esp_transport_diagnostic_busy" in diag_block

    terminal_block_start = main.index("static void ESP_TX_HandleTerminal")
    terminal_block_end = main.index("/* Phase 1:", terminal_block_start)
    terminal_block = main[terminal_block_start:terminal_block_end]
    assert "terminal_tag == CIPSEND_TX_TAG_DIAG" in terminal_block
    assert "esp_transport_diagnostic_consume_response" in terminal_block

    queued_start = main.index("static void ESP_SendQueuedFrames")
    queued_end = main.index("/******************************************************************************", queued_start)
    queued_block = main[queued_start:queued_end]
    assert "esp_transport_diagnostic_busy" in queued_block
    assert "esp_transport_diagnostic_response_ready" in queued_block
