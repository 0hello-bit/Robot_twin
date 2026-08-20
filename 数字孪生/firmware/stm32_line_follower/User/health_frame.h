#ifndef HEALTH_FRAME_H
#define HEALTH_FRAME_H

#include <stdint.h>

/* ── 0x02 健康诊断帧（firmware health baseline）─────────────────────────
 *
 * 帧骨架：AA 55 type(0x02) len(0x6A=106) [payload 106B] XOR checksum
 * 总长 111B ≤ CIPSEND_TX_MAX_DATA(145)。字节布局见设计 §5.2，全部 LE。
 * 本模块为纯编码器（无硬件依赖），黄金向量由 Host C 与 Python 双侧断言。
 */

#define HEALTH_FRAME_TYPE        0x02U
#define HEALTH_FRAME_PAYLOAD_LEN 106U
#define HEALTH_FRAME_TOTAL_LEN   111U

/* fw_schema_version：0x02 布局的语义版本，布局变化必升。 */
#define HEALTH_FRAME_FW_SCHEMA_VERSION 1U
/* fw_build_id：编译期手动设定，非日期；单一来源。
   Build 2 is the offline telemetry-throughput remediation image and must be
   distinguishable from the previously flashed Build 1 image. */
/* Build 3: IMU identity-diagnostic image. */
/* Build 4: stage-timing diagnostic image. */
/* Build 5: timing-diagnostic CIPSEND priority repair. */
#define FW_BUILD_ID 5U

/* motion_state 枚举（设计 §5.5）。 */
#define HEALTH_MOTION_STATE_INIT      0U
#define HEALTH_MOTION_STATE_RUNNING   1U
#define HEALTH_MOTION_STATE_STOPPED   2U
#define HEALTH_MOTION_STATE_TIMEOUT   3U
#define HEALTH_MOTION_STATE_LINE_LOST 4U
#define HEALTH_MOTION_STATE_UNKNOWN   255U

/* heartbeat_last_reason 枚举（设计 §5.5）。 */
#define HEALTH_HEARTBEAT_REASON_NONE             0U
#define HEALTH_HEARTBEAT_REASON_LEGACY_TIMEOUT   1U
#define HEALTH_HEARTBEAT_REASON_HEARTBEAT        2U
#define HEALTH_HEARTBEAT_REASON_STOP             3U
#define HEALTH_HEARTBEAT_REASON_RESTORE_BASELINE 4U
#define HEALTH_HEARTBEAT_REASON_LINE_LOST        5U

/* 快照字段与设计 §5.2 布局一一对应（offset 为帧内偏移；u16/u32 均 LE）。
   编码器逐字段写入，不用 memcpy 结构体（规避对齐/填充）。 */
typedef struct {
    uint8_t  fw_schema_version;        /* off 4  */
    uint8_t  fw_build_id;              /* off 5  */
    uint8_t  reset_cause;              /* off 6  */
    uint8_t  motion_state;             /* off 7  */
    uint8_t  lease_active;             /* off 8  */
    uint8_t  heartbeat_last_reason;    /* off 9  */
    uint16_t heartbeat_timeout_count;  /* off 10 */
    uint16_t heartbeat_count;          /* off 12 */
    uint32_t heartbeat_age_ms;         /* off 14 */
    uint32_t connection_generation;    /* off 18 */
    uint32_t snapshot_tick_ms;         /* off 22 */
    uint32_t loop_seq;                 /* off 26 */
    uint16_t loop_last_gap_ms;         /* off 30 */
    uint16_t loop_max_gap_ms;          /* off 32 */
    uint16_t telemetry_generated;      /* off 34 */
    uint16_t telemetry_overwritten;    /* off 36 */
    uint16_t telemetry_tx_started;     /* off 38 */
    uint16_t telemetry_tx_ok;          /* off 40 */
    uint16_t telemetry_tx_failed;      /* off 42 */
    uint16_t cipsend_started;          /* off 44 */
    uint16_t cipsend_completed;        /* off 46 */
    uint16_t cipsend_ok;               /* off 48 */
    uint16_t cipsend_error;            /* off 50 */
    uint16_t cipsend_prompt_timeout;   /* off 52 */
    uint16_t cipsend_sendok_timeout;   /* off 54 */
    uint16_t cipsend_closed;           /* off 56 */
    uint32_t cipsend_last_duration_ms; /* off 58 */
    uint32_t cipsend_max_duration_ms;  /* off 62 */
    uint16_t ack_started;              /* off 66 */
    uint16_t status_started;           /* off 68 */
    uint16_t telemetry_started;        /* off 70 */
    uint16_t diag_health_started;      /* off 72 */
    uint16_t status_retry;             /* off 74 */
    uint16_t ack_retry;                /* off 76 */
    uint16_t boundary_aborts;          /* off 78 */
    uint32_t uart_rx_bytes;            /* off 80 */
    uint32_t uart_tx_bytes;            /* off 84 */
    uint16_t uart_rx_overflow;         /* off 88 */
    uint16_t uart_tx_overflow;         /* off 90 */
    uint16_t uart_ore_events;          /* off 92 */
    uint16_t uart_rx_high_water;       /* off 94 */
    uint16_t uart_tx_high_water;       /* off 96 */
    uint16_t health_generated;         /* off 98 */
    uint16_t health_dropped;           /* off 100 */
    uint16_t health_started;           /* off 102 */
    uint16_t health_ok;                /* off 104 */
    uint16_t health_failed;            /* off 106 */
    uint16_t health_last_duration_ms;  /* off 108 */
} HealthSnapshot;

/* 返回帧总长（恒 111）。逐字段 LE 写入；checksum = type ^ len ^ payload[i]。 */
uint8_t health_frame_encode(uint8_t *buf, const HealthSnapshot *snap);

/* P0-1：RCC->CSR 原始 u32 → 0x02 协议 reset_cause u8。
   STM32F1 复位标志在 CSR 高字节（stm32f10x.h：RMVF b24 / PINRSTF b26 /
   PORRSTF b27 / SFTRSTF b28 / IWDGRSTF b29 / WWDGRSTF b30 / LPWRRSTF b31），
   低位是 LSI 状态（LSION/LSIRDY）。映射保留高字节 flag 原位、仅清 RMVF(b24)
   与保留位(b25)：`(csr >> 24) & 0xFC` → PIN->0x04 POR->0x08 SFT->0x10
   IWDG->0x20 WWDG->0x40 LPWR->0x80 RMVF->0x00，多标志按位组合。
   纯函数（无硬件依赖），main() 在写 RMVF 清标志前调用。 */
uint8_t health_reset_cause_from_csr(uint32_t csr);

#endif /* HEALTH_FRAME_H */
