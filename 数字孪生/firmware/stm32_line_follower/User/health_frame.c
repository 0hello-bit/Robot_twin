#include "health_frame.h"

/* 逐字段 LE 编码器。采用与 motor_reg_diag 相同的 put_u16_le/put_u32_le
   风格，不用 memcpy 结构体，规避结构体对齐/填充。 */

static void put_u8(uint8_t *buf, uint8_t value)
{
    buf[0] = value;
}

static void put_u16_le(uint8_t *buf, uint16_t value)
{
    buf[0] = (uint8_t)(value & 0xFFU);
    buf[1] = (uint8_t)((value >> 8) & 0xFFU);
}

static void put_u32_le(uint8_t *buf, uint32_t value)
{
    buf[0] = (uint8_t)(value & 0xFFU);
    buf[1] = (uint8_t)((value >> 8) & 0xFFU);
    buf[2] = (uint8_t)((value >> 16) & 0xFFU);
    buf[3] = (uint8_t)((value >> 24) & 0xFFU);
}

uint8_t health_reset_cause_from_csr(uint32_t csr)
{
    /* STM32F1 RCC_CSR（stm32f10x.h）：复位标志占高字节，低位是 LSI 状态。
       映射保留高字节中各 flag 的原位，仅清掉 RMVF(bit24) 与保留位(bit25)：
       (csr >> 24) & 0xFC → PIN(b26)=0x04 POR(b27)=0x08 SFT(b28)=0x10
       IWDG(b29)=0x20 WWDG(b30)=0x40 LPWR(b31)=0x80，多标志按位组合。
       旧实现 & 0x3F 会把 RMVF 误报为复位原因、丢弃 WWDG/LPWR。 */
    return (uint8_t)((csr >> 24U) & 0xFCU);
}

uint8_t health_frame_encode(uint8_t *buf, const HealthSnapshot *snap)
{
    uint8_t cs;
    uint8_t i;

    buf[0] = 0xAA;
    buf[1] = 0x55;
    buf[2] = HEALTH_FRAME_TYPE;
    buf[3] = HEALTH_FRAME_PAYLOAD_LEN;

    put_u8(buf + 4, snap->fw_schema_version);
    put_u8(buf + 5, snap->fw_build_id);
    put_u8(buf + 6, snap->reset_cause);
    put_u8(buf + 7, snap->motion_state);
    put_u8(buf + 8, snap->lease_active);
    put_u8(buf + 9, snap->heartbeat_last_reason);
    put_u16_le(buf + 10, snap->heartbeat_timeout_count);
    put_u16_le(buf + 12, snap->heartbeat_count);
    put_u32_le(buf + 14, snap->heartbeat_age_ms);
    put_u32_le(buf + 18, snap->connection_generation);
    put_u32_le(buf + 22, snap->snapshot_tick_ms);
    put_u32_le(buf + 26, snap->loop_seq);
    put_u16_le(buf + 30, snap->loop_last_gap_ms);
    put_u16_le(buf + 32, snap->loop_max_gap_ms);
    put_u16_le(buf + 34, snap->telemetry_generated);
    put_u16_le(buf + 36, snap->telemetry_overwritten);
    put_u16_le(buf + 38, snap->telemetry_tx_started);
    put_u16_le(buf + 40, snap->telemetry_tx_ok);
    put_u16_le(buf + 42, snap->telemetry_tx_failed);
    put_u16_le(buf + 44, snap->cipsend_started);
    put_u16_le(buf + 46, snap->cipsend_completed);
    put_u16_le(buf + 48, snap->cipsend_ok);
    put_u16_le(buf + 50, snap->cipsend_error);
    put_u16_le(buf + 52, snap->cipsend_prompt_timeout);
    put_u16_le(buf + 54, snap->cipsend_sendok_timeout);
    put_u16_le(buf + 56, snap->cipsend_closed);
    put_u32_le(buf + 58, snap->cipsend_last_duration_ms);
    put_u32_le(buf + 62, snap->cipsend_max_duration_ms);
    put_u16_le(buf + 66, snap->ack_started);
    put_u16_le(buf + 68, snap->status_started);
    put_u16_le(buf + 70, snap->telemetry_started);
    put_u16_le(buf + 72, snap->diag_health_started);
    put_u16_le(buf + 74, snap->status_retry);
    put_u16_le(buf + 76, snap->ack_retry);
    put_u16_le(buf + 78, snap->boundary_aborts);
    put_u32_le(buf + 80, snap->uart_rx_bytes);
    put_u32_le(buf + 84, snap->uart_tx_bytes);
    put_u16_le(buf + 88, snap->uart_rx_overflow);
    put_u16_le(buf + 90, snap->uart_tx_overflow);
    put_u16_le(buf + 92, snap->uart_ore_events);
    put_u16_le(buf + 94, snap->uart_rx_high_water);
    put_u16_le(buf + 96, snap->uart_tx_high_water);
    put_u16_le(buf + 98, snap->health_generated);
    put_u16_le(buf + 100, snap->health_dropped);
    put_u16_le(buf + 102, snap->health_started);
    put_u16_le(buf + 104, snap->health_ok);
    put_u16_le(buf + 106, snap->health_failed);
    put_u16_le(buf + 108, snap->health_last_duration_ms);

    cs = HEALTH_FRAME_TYPE ^ HEALTH_FRAME_PAYLOAD_LEN;
    for (i = 0; i < HEALTH_FRAME_PAYLOAD_LEN; i++) {
        cs ^= buf[4 + i];
    }
    buf[110] = cs;

    return HEALTH_FRAME_TOTAL_LEN;
}
