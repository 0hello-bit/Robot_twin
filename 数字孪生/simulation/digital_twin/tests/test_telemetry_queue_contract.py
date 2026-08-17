from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
HEADER = PROJECT_ROOT / "firmware" / "stm32_line_follower" / "User" / \
    "telemetry_batch.h"
MAIN_C = PROJECT_ROOT / "firmware" / "stm32_line_follower" / "User" / "main.c"
CIPSEND_TX_H = PROJECT_ROOT / "firmware" / "stm32_line_follower" / "User" / \
    "cipsend_tx.h"


def test_tcp_batch_capacity_matches_42_byte_payload_contract():
    header = HEADER.read_text(encoding="utf-8")

    assert "#define TELEMETRY_BATCH_FRAME_SIZE 47U" in header
    assert "#define TELEMETRY_BATCH_MAX_FRAMES 16U" in header
    assert "#define TELEMETRY_BATCH_SEND_MAX_FRAMES 5U" in header
    assert "(TELEMETRY_BATCH_FRAME_SIZE * TELEMETRY_BATCH_MAX_FRAMES)" in header
    assert "(TELEMETRY_BATCH_FRAME_SIZE * TELEMETRY_BATCH_SEND_MAX_FRAMES)" in header
    cipsend = CIPSEND_TX_H.read_text(encoding="utf-8")
    assert "#define CIPSEND_TX_MAX_DATA  248U" in cipsend


def test_main_encodes_extended_telemetry_fields_at_approved_offsets():
    source = MAIN_C.read_text(encoding="utf-8")

    assert "uint8_t len  = 42;" in source
    for offset in range(30, 46):
        assert f"s_tele_frame[{offset}]" in source
    assert "s_tele_frame[46] = cs" in source
    assert "const MPU6050_Data *imu_snapshot" in source
    assert "sample_seq" in source
    assert "s_telemetry_sample_seq++" in source
    assert "MPU6050_GetInitStatus()" in source
    assert "for (i = 4; i < 46; i++)" in source


def test_all_three_telemetry_paths_use_the_extended_snapshot():
    source = MAIN_C.read_text(encoding="utf-8")
    assert source.count("Telemetry_Queue(") == 4
    assert source.count("telemetry_imu = mpu_data;") == 3
    assert source.count("&telemetry_imu") == 3
