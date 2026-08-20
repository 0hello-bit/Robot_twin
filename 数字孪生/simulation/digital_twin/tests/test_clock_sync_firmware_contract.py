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
    assert "twin_control_receive_byte_timed" in transport
    assert "esp_transport_process_byte_at" in transport
    assert "esp_transport_peek_pending_clock_sync" in main
    assert "esp_transport_consume_pending_clock_sync" in main
    assert "CIPSEND_TX_TAG_TELEMETRY" in main
    assert "twin_control_encode_clock_sync" in protocol

    clock_block_start = main.index("/* --- Clock sync response")
    clock_block_end = main.index("/* --- Telemetry", clock_block_start)
    clock_block = main[clock_block_start:clock_block_end]
    assert "CIPSEND_TX_TAG_TELEMETRY" not in clock_block
    helper_start = main.index("static uint8_t ESP_TrySendClockSync")
    helper_end = main.index("/* Phase 2+3", helper_start)
    helper_block = main[helper_start:helper_end]
    assert "CIPSEND_TX_TAG_CLOCK_SYNC" in helper_block


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

    helper_start = main.index("static uint8_t ESP_TrySendClockSync")
    helper_end = main.index("/* Phase 2+3", helper_start)
    helper_block = main[helper_start:helper_end]
    assert "CIPSEND_TX_TAG_CLOCK_SYNC" in helper_block
    assert "CIPSEND_TX_TAG_DIAG" not in clock_block
    assert "terminal_tag == CIPSEND_TX_TAG_CLOCK_SYNC" in terminal_block
    assert "tag = CIPSEND_TX_TAG_DIAG" in diag_block


def test_firmware_joins_the_current_2_4ghz_lan_for_tcp_testing():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    assert '#define WIFI_SSID   "HUAWEI-1CR2M9"' in main
    assert '#define WIFI_PWD    "xiang87777114"' in main
    assert '#define TCP_PORT    8888' in main


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


def test_droppable_paths_block_while_clock_sync_is_pending():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    telemetry_start = main.index("static void ESP_TrySendTelemetry")
    telemetry_end = main.index("/* 遥测入队", telemetry_start)
    diag_start = main.index("static uint8_t ESP_SendDiagFrame")
    diag_end = main.index("static void ESP_TrySendImuDiagnostic", diag_start)
    health_start = main.index("static void health_emit")
    health_end = main.index("static void ESP_DrainPendingStatus", health_start)

    for block in (
        main[telemetry_start:telemetry_end],
        main[diag_start:diag_end],
        main[health_start:health_end],
    ):
        assert "esp_transport_has_pending_clock_sync" in block

    telemetry_block = main[telemetry_start:telemetry_end]
    diag_block = main[diag_start:diag_end]
    assert telemetry_block.index("esp_transport_has_pending_clock_sync") < telemetry_block.index(
        "cipsend_tx_start("
    )
    assert diag_block.index("esp_transport_has_pending_clock_sync") < diag_block.index(
        "cipsend_tx_start("
    )
    assert health_start < main.index("ESP_SendDiagFrame", health_start)
    health_flush_start = main.index("static void health_flush_pending")
    health_flush_end = main.index("static void ESP_DrainPendingStatus", health_flush_start)
    health_flush_block = main[health_flush_start:health_flush_end]
    assert health_flush_block.index("esp_transport_has_pending_clock_sync") < health_flush_block.index(
        "ESP_SendDiagFrame"
    )


def test_disconnect_event_survives_closed_then_connect_in_one_rx_drain():
    transport = (FIRMWARE / "esp_runtime_transport.c").read_text(encoding="utf-8")
    clear_start = transport.index("static void clear_pending_frames")
    clear_end = transport.index("static void process_at_line", clear_start)
    clear_block = transport[clear_start:clear_end]
    assert "s_disconnect_event = 0U" not in clear_block


def test_closed_event_reaches_main_timing_state_reset():
    header = (FIRMWARE / "esp_runtime_transport.h").read_text(encoding="utf-8")
    transport = (FIRMWARE / "esp_runtime_transport.c").read_text(encoding="utf-8")
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    assert "esp_transport_take_disconnect_event" in header
    assert "s_disconnect_event = 1U" in transport
    service_start = main.index("static void ESP_ServiceTX")
    service_end = main.index("/* 构建 31 字节遥测帧", service_start)
    service_block = main[service_start:service_end]
    assert "esp_transport_take_disconnect_event" in service_block
    assert "reset_timing_diagnostic_state" in service_block


def test_timing_diagnostic_state_is_cleared_at_connection_boundaries():
    main = (FIRMWARE / "main.c").read_text(encoding="utf-8")

    disconnected_start = main.index("static void ESP_MarkDisconnected")
    disconnected_end = main.index("/* 终态处理", disconnected_start)
    disconnected_block = main[disconnected_start:disconnected_end]
    service_start = main.index("static void ESP_ServiceTX")
    service_end = main.index("/* 构建 31 字节遥测帧", service_start)
    service_block = main[service_start:service_end]

    for block in (disconnected_block, service_block):
        assert "reset_timing_diagnostic_state" in block


def test_esp_capability_diagnostic_is_deferred_from_tcp_only_firmware():
    """The separate ESP AT capability channel is outside this firmware change."""
    project = (FIRMWARE.parent / "project.uvprojx").read_text(encoding="utf-8")
    assert "esp_at_diagnostic.c" not in project
    assert "esp_at_diagnostic.h" not in project
    assert not (FIRMWARE / "esp_at_diagnostic.c").exists()
    assert not (FIRMWARE / "esp_at_diagnostic.h").exists()
