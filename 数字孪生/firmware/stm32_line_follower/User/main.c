#include "stm32f10x.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "Delay.h"
#include "Motor.h"
#include "Sensor.h"
#include "mpu6050.h"
#include "twin_control_protocol.h"
#include "esp_runtime_transport.h"
#include "uart_ring.h"
#include "motor_register_diag.h"
#include "imu_diagnostic.h"
#include "diag_one_shot.h"
#include "send_response_parser.h"
#include "cipsend_transaction.h"
#include "cipsend_tx.h"
#include "tx_frame_queue.h"
#include "esp_tx_coordinator.h"
#include "mono_time.h"
#include "mono_time_core.h"
#include "health_stats.h"
#include "health_frame.h"
#include "health_watchdog.h"
#include "telemetry_batch.h"
#include "telemetry_rate.h"

/******************************************************************************
 * ESP01S WiFi (TCP Server)
 ******************************************************************************/
#define WIFI_SSID   "@Ruijie-sC384"
#define WIFI_PWD    "xiang87777114"
#define TCP_PORT    8888

static void USART1_Init(uint32_t baud)
{
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_USART1 | RCC_APB2Periph_GPIOA, ENABLE);
    GPIO_InitTypeDef gpio;
    gpio.GPIO_Pin = GPIO_Pin_9;
    gpio.GPIO_Mode = GPIO_Mode_AF_PP;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOA, &gpio);
    gpio.GPIO_Pin = GPIO_Pin_10;
    gpio.GPIO_Mode = GPIO_Mode_IN_FLOATING;
    GPIO_Init(GPIOA, &gpio);
    USART_InitTypeDef usart;
    usart.USART_BaudRate = baud;
    usart.USART_WordLength = USART_WordLength_8b;
    usart.USART_StopBits = USART_StopBits_1;
    usart.USART_Parity = USART_Parity_No;
    usart.USART_HardwareFlowControl = USART_HardwareFlowControl_None;
    usart.USART_Mode = USART_Mode_Tx | USART_Mode_Rx;
    USART_Init(USART1, &usart);
    USART_Cmd(USART1, ENABLE);
}

static void ESP_Send(const char *cmd)
{
    while (*cmd) {
        while (USART_GetFlagStatus(USART1, USART_FLAG_TXE) == RESET);
        USART_SendData(USART1, *cmd++);
    }
    while (USART_GetFlagStatus(USART1, USART_FLAG_TXE) == RESET);
    USART_SendData(USART1, '\r');
    while (USART_GetFlagStatus(USART1, USART_FLAG_TXE) == RESET);
    USART_SendData(USART1, '\n');
}

static void ESP_Flush(void)
{
    uint32_t t;
    for (t = 0; t < 200; t++)
        if (USART_GetFlagStatus(USART1, USART_FLAG_RXNE) != RESET)
            USART_ReceiveData(USART1);
}

#define STR(x) _STR(x)
#define _STR(x) #x

static void ESP_MarkDisconnected(void);

static void ESP_Setup(void)
{
    ESP_Flush();
    ESP_Send("AT");                    Delay_ms(1500);  ESP_Flush();
    ESP_Send("AT+CWMODE=1");           Delay_ms(1500);  ESP_Flush();
    ESP_Send("AT+CWJAP=\"" WIFI_SSID "\",\"" WIFI_PWD "\"");
                                       Delay_ms(10000); ESP_Flush();
    ESP_Send("AT+CIPMUX=1");           Delay_ms(1500);  ESP_Flush();
    ESP_Send("AT+CIPMODE=0");           Delay_ms(500);   ESP_Flush();
    ESP_Send("AT+CIPSERVER=1," STR(TCP_PORT));
                                       Delay_ms(1500);  ESP_Flush();
    ESP_MarkDisconnected();
}

/******************************************************************************
 * 遥测帧 (二进制协议, 与 wifi_bridge.py 对接)
 * 帧格式: 0xAA 0x55 TYPE LEN [payload] XOR_CHECKSUM
 ******************************************************************************/
static volatile uint8_t g_tcp_client_id = 0xFF;
static volatile uint8_t g_tcp_client_connected = 0;

/* SPSC UART RX ring — ISR pushes, main loop pops (control input path). */
UartRing g_uart_ring;
/* SPSC UART TX ring — main loop pushes, ISR pops (non-blocking TX). */
UartRing g_uart_tx_ring;
static uint8_t g_prev_connected = 0;

/* Retry buffers for critical A (ACK) and S (status) frames, scoped to the
   current connection generation (tx_frame_queue.h).  After a failed CIPSEND
   transaction, the frame is preserved here (not consumed from the transport
   layer retry buffer) so it can be retried on the next main-loop iteration.
   Telemetry and diagnostic frames are NOT retried — only A/S frames.
   On a new CONNECT (generation change) or a CLOSED terminal result, all
   retained frames are dropped so old critical frames are never sent to a
   new client (Task 4B-4 fix, Codex review remediation). */
static TxFrameQueue g_tx_queue;

/* Diagnostic one-shot state machine: arms exactly once on each transition
   from motion-inhibited to running.  Declared at file scope so both the
   inhibited branch and the running branch can update it. */
static DiagOneShot g_diag_state;

/* ── Task 4B-4 fix: 非阻塞 CIPSEND TX 状态机 ─────────────────────────
   CIPSEND 从同步阻塞 while 改为持久化非阻塞状态机（cipsend_tx.h）。
   同一时间只允许一个事务；每次主循环由 ESP_TX_Service 推进一小步。
   A/S 为高优先级可靠帧（重试缓冲）；telemetry/diag 可丢。 */

static CipsendTx g_cipsend_tx;

/* ── Task 4B-4 final fix: TX connection-boundary coordinator ──────────
   Single call site for all boundary-abort decisions.  Ensures no byte
   from the old connection epoch reaches the ESP UART after a new client
   CONNECTs.  See esp_tx_coordinator.h and tx_boundary_design_decision.md. */
static EspTxCoordinator g_coordinator;

/* ── Health baseline: 0x02 健康统计（主上下文单写者）。 ──────────────── */
static HealthStats g_health_stats;
static uint8_t g_reset_cause = 0U;      /* RCC->CSR 复位原因快照（开机读+清 RMVF） */
static uint32_t s_last_health_ms = 0U;  /* 1Hz health_emit 上次发射时刻 */
static uint8_t  s_health_frame[HEALTH_FRAME_TOTAL_LEN]; /* 延迟待发的 0x02 健康帧 */
static uint32_t s_last_tx_generation = 0U; /* 上次看到的连接代次（发送仲裁） */

/* TX-ring discard callback for the coordinator: disable TXE, drain the
   ring, leave TXE disabled.  uart_tx_sink re-enables TXE on next push.
   Returns the number of bytes discarded (observable). */
static uint16_t discard_tx_ring_cb(void *ctx)
{
    uint8_t dummy;
    uint16_t discarded = 0U;
    (void)ctx;
    USART_ITConfig(USART1, USART_IT_TXE, DISABLE);
    while (uart_ring_pop(&g_uart_tx_ring, &dummy)) {
        discarded++;
    }
    return discarded;
}

/* 遥测批量槽：最多保留最新 8 帧，ESP 忙时只丢可丢的最旧遥测。 */
static uint8_t s_tele_frame[TELEMETRY_BATCH_FRAME_SIZE];
static TelemetryBatch s_tele_batch;
/* Droppable TX is released only after the current sensor/control phase. */
static uint8_t s_control_cycle_ready;
/* Keep the boot-time IMU identity observable until an existing client accepts
   one diagnostic frame. */
static uint8_t s_imu_diag_pending = 1U;

/* 真实单调时间（mono_time.h / mono_time_core.h）。 */
static uint32_t s_last_telemetry_ms = 0U;
static uint32_t s_last_yaw_ms = 0U;

/* yaw dt 边界保护（ms）：零 dt 钳到 min，异常大间隔钳到 max。 */
#define YAW_DT_MIN_MS  1U
#define YAW_DT_MAX_MS  100U

/* UART TX 字节 sink：压入 TX ring 并启用 TXE 中断（非阻塞）。 */
static uint8_t uart_tx_sink(void *ctx, uint8_t byte)
{
    (void)ctx;
    if (!uart_ring_push(&g_uart_tx_ring, byte)) return 0U;
    USART_ITConfig(USART1, USART_IT_TXE, ENABLE);
    return 1U;
}

static void clear_telemetry_batch_cb(void *ctx)
{
    telemetry_batch_clear((TelemetryBatch *)ctx);
}

static void build_cipsend_cmd(char *cmd, uint16_t len)
{
    sprintf(cmd, "AT+CIPSEND=%d,%d\r\n", (int)g_tcp_client_id, (int)len);
}

static void ESP_MarkDisconnected(void)
{
    g_tcp_client_id = 0xFF;
    g_tcp_client_connected = 0;
    hstats_health_epoch_changed(&g_health_stats);  /* 断连 → 放弃待发健康帧 */
    twin_control_timeout();
}

/* 终态处理：成功清对应重试缓冲；ERROR/busy/超时保留（同代次内重试）；
   CLOSED 丢弃全部保留帧 + 强制 abort TX ring（连接已断，不得泄漏到
   下一连接）。等下一个 CONNECT 到来时 coordinator 会再做完整边界清理。 */
static void ESP_TX_HandleTerminal(void)
{
    uint8_t terminal_tag = CIPSEND_TX_TAG_NONE;
    uint8_t terminal_result = CTS_RESULT_NONE;

    /* Starting CIPSEND is not delivery evidence; wait for SEND OK. */
    if (cipsend_tx_is_terminal(&g_cipsend_tx)) {
        terminal_tag = cipsend_tx_tag(&g_cipsend_tx);
        terminal_result = cipsend_tx_result(&g_cipsend_tx);
    }

    /* Delegates to the extracted pure-logic function in esp_tx_coordinator,
       which is Host-testable via the same production code path.  See
       tx_boundary_design_decision.md §4 and §9. */
    etc_handle_terminal(&g_coordinator, mono_now_ms());

    if (imu_diagnostic_delivery_confirmed(terminal_tag, terminal_result)) {
        s_imu_diag_pending = 0U;
    }
}

/* Phase 1: drain RX ring, route every byte to both the transport
   (CONNECT/CLOSED/+IPD) and the TX state machine ('>' / SEND OK parse). */
static void ESP_ServiceRX(void)
{
    uint8_t ch;
    while (uart_ring_pop(&g_uart_ring, &ch)) {
        esp_transport_process_byte(ch);        /* CONNECT/CLOSED/+IPD 输入路径 */
        cipsend_tx_feed_byte(&g_cipsend_tx, ch); /* TX 事务 '>' / SEND OK 解析 */
    }
}

/* Phase 2+3: check connection boundary, then push TX + handle terminal.
   Must run AFTER ESP_ServiceRX (which may have detected CONNECT/CLOSED)
   but BEFORE any main-loop logic that reads connection state. */
static void ESP_ServiceTX(void)
{
    uint32_t gen;
    /* Check boundary BEFORE pushing any TX bytes (see design decision §5).
       If a CONNECT arrived during ESP_ServiceRX, the coordinator discards
       the old CipsendTx, TX ring, tele slot, and A/S retry buffers so no
       old-epoch byte can reach the ESP. */
    (void)etc_check_boundary(&g_coordinator,
                             esp_transport_connection_generation(),
                             mono_now_ms());
    /* 连接代次变化 → 放弃旧代次待发健康帧（发送仲裁，不得发给新客户端）。 */
    gen = esp_transport_connection_generation();
    if (gen != s_last_tx_generation) {
        s_last_tx_generation = gen;
        hstats_health_epoch_changed(&g_health_stats);
    }
    cipsend_tx_tick(&g_cipsend_tx, mono_now_ms(), uart_tx_sink, NULL);
    ESP_TX_HandleTerminal();
}

/* 构建 31 字节遥测帧到 s_tele_frame（兼容旧 payload 布局）。 */
static void build_telemetry_frame(int16_t s0, int16_t s1, int16_t s2, int16_t s3,
                                   int16_t m1, int16_t m2, int16_t m3, int16_t m4,
                                   int16_t error, int16_t pid_output,
                                   uint32_t tick, int32_t yaw,
                                   uint8_t imu_validity)
{
    uint8_t type = 0x01;
    uint8_t len  = 26;
    uint8_t cs   = type ^ len;
    uint8_t i;
    int32_t yaw_int = yaw;

    s_tele_frame[4]  = (uint8_t)(s0 & 0xFF);
    s_tele_frame[5]  = (uint8_t)(s1 & 0xFF);
    s_tele_frame[6]  = (uint8_t)(s2 & 0xFF);
    s_tele_frame[7]  = (uint8_t)(s3 & 0xFF);
    s_tele_frame[8]  = (uint8_t)(m1 & 0xFF);        s_tele_frame[9]  = (uint8_t)((m1 >> 8) & 0xFF);
    s_tele_frame[10] = (uint8_t)(m2 & 0xFF);        s_tele_frame[11] = (uint8_t)((m2 >> 8) & 0xFF);
    s_tele_frame[12] = (uint8_t)(m3 & 0xFF);        s_tele_frame[13] = (uint8_t)((m3 >> 8) & 0xFF);
    s_tele_frame[14] = (uint8_t)(m4 & 0xFF);        s_tele_frame[15] = (uint8_t)((m4 >> 8) & 0xFF);
    s_tele_frame[16] = (uint8_t)(error & 0xFF);     s_tele_frame[17] = (uint8_t)((error >> 8) & 0xFF);
    s_tele_frame[18] = (uint8_t)(pid_output & 0xFF);s_tele_frame[19] = (uint8_t)((pid_output >> 8) & 0xFF);
    s_tele_frame[20] = (uint8_t)(tick & 0xFF);
    s_tele_frame[21] = (uint8_t)((tick >> 8) & 0xFF);
    s_tele_frame[22] = (uint8_t)((tick >> 16) & 0xFF);
    s_tele_frame[23] = (uint8_t)((tick >> 24) & 0xFF);
    s_tele_frame[24] = (uint8_t)(yaw_int & 0xFF);
    s_tele_frame[25] = (uint8_t)((yaw_int >> 8) & 0xFF);
    s_tele_frame[26] = (uint8_t)((yaw_int >> 16) & 0xFF);
    s_tele_frame[27] = (uint8_t)((yaw_int >> 24) & 0xFF);
    s_tele_frame[28] = imu_validity;
    s_tele_frame[29] = MPU6050_GetInitStatus();

    for (i = 4; i < 30; i++) cs ^= s_tele_frame[i];

    s_tele_frame[0] = 0xAA;
    s_tele_frame[1] = 0x55;
    s_tele_frame[2] = type;
    s_tele_frame[3] = len;
    s_tele_frame[30] = cs;
}

/* 尝试把待发遥测交给 TX 状态机（仅当空闲且无 critical 待发）。 */
static void ESP_TrySendTelemetry(void)
{
    char cmd[24];
    uint16_t batch_len;
    if (!telemetry_batch_has_data(&s_tele_batch)) return;
    if (hstats_health_due(&g_health_stats)) return;  /* 健康帧优先：让行（仲裁） */
    if (cipsend_tx_busy(&g_cipsend_tx)) return;
    if (twin_control_has_pending_status()) return;
    if (!etc_telemetry_dispatch_allowed(
            s_control_cycle_ready,
            txfq_has_retry(&g_tx_queue),
            esp_transport_has_pending_ack(),
            esp_transport_has_pending_status(),
            twin_control_has_pending_status())) {
        return;  /* A/S 优先, including frames queued later this loop */
    }
    batch_len = telemetry_batch_length(&s_tele_batch);
    build_cipsend_cmd(cmd, batch_len);
    if (cipsend_tx_start(&g_cipsend_tx, cmd, (uint16_t)strlen(cmd),
                         telemetry_batch_data(&s_tele_batch), batch_len,
                         CIPSEND_TX_PRIORITY_DROPPABLE, CIPSEND_TX_TAG_TELEMETRY,
                         mono_now_ms())) {
        telemetry_batch_consume(&s_tele_batch);
        hstats_tx_started(&g_health_stats, CIPSEND_TX_TAG_TELEMETRY,
                          mono_now_ms());
    }
}

/* 遥测入队（latest-eight）：由 ESP_TrySendTelemetry 择机批量发送。
   tick 为采样时的真实单调毫秒（mono_now_ms），不再是 g_loop_count*5。 */
static void Telemetry_Queue(int16_t s0, int16_t s1, int16_t s2, int16_t s3,
                            int16_t m1, int16_t m2, int16_t m3, int16_t m4,
                            int16_t error, int16_t pid_output,
                            uint32_t tick, int32_t yaw,
                            uint8_t imu_validity)
{
    uint8_t overwrote;
    if (!g_tcp_client_connected || g_tcp_client_id > 4) {
        telemetry_batch_clear(&s_tele_batch);
        return;
    }
    build_telemetry_frame(s0, s1, s2, s3, m1, m2, m3, m4,
                          error, pid_output, tick, yaw, imu_validity);
    if (telemetry_batch_append(&s_tele_batch, s_tele_frame,
                               TELEMETRY_BATCH_FRAME_SIZE, &overwrote)) {
        hstats_telemetry_generated(&g_health_stats);
        if (overwrote) hstats_telemetry_overwritten(&g_health_stats);
        ESP_TrySendTelemetry();
    }
}

/* 发送二进制诊断帧。0x7E 旧诊断帧可丢弃；0x7D IMU 身份诊断帧
   保留到 SEND OK。若 TX 忙则本次放弃。
   Health baseline: 0x02 健康帧走 CIPSEND_TX_TAG_DIAG_HEALTH（专属归属）；
   0x7E 旧诊断帧仍走 CIPSEND_TX_TAG_DIAG。返回是否成功开启事务（start
   成功处触发 hstats_tx_started；失败由调用方记 health_dropped）。 */
static uint8_t ESP_SendDiagFrame(const uint8_t *frame, uint16_t frame_len)
{
    uint8_t tag;
    uint8_t started;
    char cmd[24];
    if (!g_tcp_client_connected || g_tcp_client_id > 4) return 0U;
    if (cipsend_tx_busy(&g_cipsend_tx)) return 0U;
    if (twin_control_has_pending_status()) return 0U;
    if (txfq_has_retry(&g_tx_queue)) return 0U;
    if (esp_transport_has_pending_ack()
        || esp_transport_has_pending_status()) return 0U;
    if (frame_len >= 4U && frame[2] == HEALTH_FRAME_TYPE) {
        tag = CIPSEND_TX_TAG_DIAG_HEALTH;
    } else if (frame_len >= 4U && frame[2] == IMU_DIAGNOSTIC_TYPE) {
        tag = CIPSEND_TX_TAG_IMU_DIAGNOSTIC;
    } else {
        tag = CIPSEND_TX_TAG_DIAG;
    }
    build_cipsend_cmd(cmd, frame_len);
    started = cipsend_tx_start(&g_cipsend_tx, cmd, (uint16_t)strlen(cmd),
                               frame, frame_len,
                               CIPSEND_TX_PRIORITY_DROPPABLE, tag,
                               mono_now_ms());
    if (started) {
        hstats_tx_started(&g_health_stats, tag, mono_now_ms());
    }
    return started;
}

static void ESP_TrySendImuDiagnostic(void)
{
    ImuDiagnosticSnapshot snapshot;
    uint8_t frame[IMU_DIAGNOSTIC_FRAME_SIZE];

    if (!s_imu_diag_pending) return;

    snapshot.observed_id = MPU6050_GetObservedID();
    snapshot.init_status = MPU6050_GetInitStatus();
    snapshot.validity_flags = MPU6050_GetValidityFlags();
    snapshot.hardware_observed_id = MPU6050_GetHardwareObservedID();
    imu_diagnostic_encode(frame, &snapshot);

    /* Keep the pending flag on a busy/disconnected/blocked transport so the
       identity is still sent when the existing client path becomes idle. */
    (void)ESP_SendDiagFrame(frame, IMU_DIAGNOSTIC_FRAME_SIZE);
}

/* 发送队列（非阻塞）：ACK → STATUS → telemetry，严格串行。
   每次只尝试开启一个事务；失败时 critical 重试缓冲保留到下一轮。
   critical 帧的可靠性只在当前连接代次内保证：跨连接（代次改变 /
   CLOSED）时旧 ACK/STATUS 会被 txfq 丢弃，不会发给新客户端。 */
static void ESP_SendQueuedFrames(uint8_t allow_telemetry)
{
    char cmd[24];
    uint8_t ack_was_retained;
    uint8_t status_was_retained;
    if (!g_tcp_client_connected || g_tcp_client_id > 4) return;
    if (cipsend_tx_busy(&g_cipsend_tx)) return;

    /* --- ACK: retry existing or fetch new from transport ---
       Health baseline: 取新帧前 txfq_has_ack 已真 = 重发（上笔非 OK 终态）→
       hstats_ack_retry。 */
    ack_was_retained = txfq_has_ack(&g_tx_queue);
    if (!ack_was_retained && esp_transport_has_pending_ack()) {
        char tmp[TX_FRAME_QUEUE_LINE_MAX + 1U];
        uint16_t n = esp_transport_get_pending_ack(tmp, sizeof(tmp));
        txfq_retain_ack(&g_tx_queue, tmp, n);
    }
    if (txfq_has_ack(&g_tx_queue)) {
        if (ack_was_retained) hstats_ack_retry(&g_health_stats);
        build_cipsend_cmd(cmd, txfq_ack_len(&g_tx_queue));
        if (cipsend_tx_start(&g_cipsend_tx, cmd, (uint16_t)strlen(cmd),
                             (const uint8_t *)txfq_ack_ptr(&g_tx_queue),
                             txfq_ack_len(&g_tx_queue),
                             CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK,
                             mono_now_ms())) {
            hstats_tx_started(&g_health_stats, CIPSEND_TX_TAG_ACK, mono_now_ms());
        }
        return;   /* 保持 ACK 顺序：STATUS 延后 */
    }

    /* --- STATUS: retry existing or fetch new from transport --- */
    status_was_retained = txfq_has_status(&g_tx_queue);
    if (!status_was_retained && esp_transport_has_pending_status()) {
        char tmp[TX_FRAME_QUEUE_LINE_MAX + 1U];
        uint16_t n = esp_transport_get_pending_status(tmp, sizeof(tmp));
        txfq_retain_status(&g_tx_queue, tmp, n);
    }
    if (txfq_has_status(&g_tx_queue)) {
        if (status_was_retained) hstats_status_retry(&g_health_stats);
        build_cipsend_cmd(cmd, txfq_status_len(&g_tx_queue));
        if (cipsend_tx_start(&g_cipsend_tx, cmd, (uint16_t)strlen(cmd),
                             (const uint8_t *)txfq_status_ptr(&g_tx_queue),
                             txfq_status_len(&g_tx_queue),
                             CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_STATUS,
                             mono_now_ms())) {
            hstats_tx_started(&g_health_stats, CIPSEND_TX_TAG_STATUS, mono_now_ms());
        }
        return;
    }

    /* --- Telemetry (latest-wins slot) --- */
    if (allow_telemetry) ESP_TrySendTelemetry();
}

/******************************************************************************
 * 以下为小车_改原封不动的算法 + 参数
 ******************************************************************************/

#define PID_KP                  35.0f
#define PID_KD                  10.0f

#define SPEED_MAX               680
#define SPEED_MIN               260
#define SPEED_ERR_DECAY         22.0f
#define SPEED_INIT              400.0f

#define TURN_LIMIT              600

#define ERR_OUTER               2.5f
#define ERR_INNER               0.45f

#define TURN_GAIN_K             0.9f

#define ERR_FILTER_OLD          0.65f
#define ERR_FILTER_NEW          0.35f
#define SPEED_FILTER_OLD        0.75f
#define SPEED_FILTER_NEW        0.25f
#define TURN_FILTER_OLD         0.55f
#define TURN_FILTER_NEW         0.45f
#define MOTOR_FILTER_OLD        0.15f
#define MOTOR_FILTER_NEW        0.85f

#define CURVE_REVERSE_ERR       1.0f
#define CURVE_REVERSE_POS       1
#define CURVE_INNER_REVERSE    -260
#define CURVE_MIN_TURN_EXTRA    60
#define CURVE_MID_INNER_REVERSE -120
#define CURVE_MID_TURN_EXTRA    20

#define PATTERN_LEFT_OUTER      0x08
#define PATTERN_LEFT_HEAVY      0x0C
#define PATTERN_LEFT_INNER      0x04
#define PATTERN_RIGHT_INNER     0x02
#define PATTERN_RIGHT_HEAVY     0x03
#define PATTERN_RIGHT_OUTER     0x01

#define D_LIMIT                 0.8f
#define SENSOR_STABLE_COUNT     0
#define LOST_HOLD_COUNT         3
#define LOST_FAST_OUTER         600
#define LOST_FAST_INNER        -200
#define MOTOR_LIMIT             650
#define LOOP_DELAY_MS           5

#define USART1_BAUDRATE         38400

static int clamp(int v, int min, int max)
{
    if (v > max) return max;
    if (v < min) return min;
    return v;
}

static float sm_l = 0, sm_r = 0;

static void MotorOut(int l, int r)
{
    l = clamp(l, -MOTOR_LIMIT, MOTOR_LIMIT);
    r = clamp(r, -MOTOR_LIMIT, MOTOR_LIMIT);
    sm_l = sm_l * MOTOR_FILTER_OLD + l * MOTOR_FILTER_NEW;
    sm_r = sm_r * MOTOR_FILTER_OLD + r * MOTOR_FILTER_NEW;

    if (sm_l >= 0)
    {
        Motor1_SetSpeed(0, (int)sm_l);
        Motor4_SetSpeed(0, (int)sm_l);
    }
    else
    {
        Motor1_SetSpeed(1, (int)(-sm_l));
        Motor4_SetSpeed(1, (int)(-sm_l));
    }

    if (sm_r >= 0)
    {
        Motor2_SetSpeed(0, (int)sm_r);
        Motor3_SetSpeed(0, (int)sm_r);
    }
    else
    {
        Motor2_SetSpeed(1, (int)(-sm_r));
        Motor3_SetSpeed(1, (int)(-sm_r));
    }
}

static void MotorTargetsZero(void)
{
    sm_l = 0;
    sm_r = 0;
    Motor1_SetSpeed(0, 0);
    Motor2_SetSpeed(0, 0);
    Motor3_SetSpeed(0, 0);
    Motor4_SetSpeed(0, 0);
}

/* If the one-shot diagnostic is armed, capture TIM2/TIM4 registers and send
   exactly one frame.  Call after each MotorOut call.  No effect otherwise.
   The armed flag is consumed AFTER the send attempt so a disconnected ESP
   does not permanently lose the diagnostic — but we do NOT retry on failure
   because snapshot registers may have changed by the next loop iteration. */
static void Diag_CaptureAndSendOnce(void)
{
    if (!diag_one_shot_peek(&g_diag_state)) return;

    MotorRegSnapshot snap;
    snap.regs[0]  = TIM2->CR1;
    snap.regs[1]  = TIM2->ARR;
    snap.regs[2]  = TIM2->CCR1;
    snap.regs[3]  = TIM2->CCR2;
    snap.regs[4]  = TIM2->CCR3;
    snap.regs[5]  = TIM2->CCR4;
    snap.regs[6]  = TIM4->CR1;
    snap.regs[7]  = TIM4->ARR;
    snap.regs[8]  = TIM4->CCR1;
    snap.regs[9]  = TIM4->CCR2;
    snap.regs[10] = TIM4->CCR3;
    snap.regs[11] = TIM4->CCR4;

    uint8_t diag_buf[MOTOR_REG_DIAG_FRAME_SIZE];
    motor_reg_diag_encode(diag_buf, &snap);

    /* Attempt send.  If ESP is disconnected (no TCP client), the frame
       is dropped silently.  Consume the arm regardless — we do NOT retry
       with stale register values on a later loop iteration. */
    ESP_SendDiagFrame(diag_buf, MOTOR_REG_DIAG_FRAME_SIZE);

    /* Clear the armed flag — one attempt per transition. */
    diag_one_shot_consume(&g_diag_state);
}

/* ── Health baseline: 每轮健康迭代 + 1Hz 0x02 发射 ──────────────────── */

/* 主循环每轮迭代顶部调用一次（设计 §4.1）。 */
static void health_loop_tick(uint32_t now_ms)
{
    hstats_loop_tick(&g_health_stats, now_ms);
    if (twin_control_consume_heartbeat_pending()) {
        twin_control_heartbeat(now_ms);
    }
    if (twin_control_heartbeat_tick(now_ms)) {
        MotorTargetsZero();   /* 租约到期 → 同轮四路归零 */
    }
    iwdg_feed();              /* 喂狗：证明上一轮已返回循环顶部 */
}

/* 1Hz 0x02 健康帧发射。归类顺序按 Round 3 项 3：busy 分支 generated+dropped
   后退出；可发送分支先以“截至上一笔已归类尝试”的计数填快照并编码 → 随后
   generated++ → start，成功 started++（ESP_SendDiagFrame 内部钩子）、失败
   dropped++。 */
static void health_emit(void)
{
    uint32_t now_ms = mono_now_ms();
    HealthSnapshot snap;
    uint8_t buf[HEALTH_FRAME_TOTAL_LEN];

    if ((uint32_t)(now_ms - s_last_health_ms) < 1000U) return;
    s_last_health_ms = now_ms;

    /* 先填快照（值 = 归类前计数，设计 §5.2 Round 3 项 3），再编码，再 generated++。
       （原"忙/有 A/S 重试 → 放弃"分支已改为延迟不丢，见下方 gate_defer。） */
    memset(&snap, 0, sizeof(snap));
    snap.fw_schema_version = HEALTH_FRAME_FW_SCHEMA_VERSION;
    snap.fw_build_id       = FW_BUILD_ID;
    snap.reset_cause       = g_reset_cause;
    snap.motion_state      = twin_control_health_motion_state();
    snap.lease_active      = twin_control_lease_active(now_ms);
    snap.heartbeat_last_reason = twin_control_heartbeat_last_reason();
    snap.heartbeat_timeout_count = twin_control_heartbeat_timeout_count();
    snap.heartbeat_count   = twin_control_heartbeat_count();
    snap.heartbeat_age_ms  = twin_control_heartbeat_age_ms(now_ms);
    snap.connection_generation = esp_transport_connection_generation();
    /* P0-3: boundary_aborts 单一来源 = health_stats（hstats_fill_health 从
       s->boundary_aborts 读取，coordinator do_abort 已调用 hstats_boundary_abort）。
       不再用 coordinator.boundary_events 在此覆盖（会被 fill_health 覆盖）。 */
    snap.uart_rx_bytes     = g_uart_ring.rx_bytes;
    snap.uart_tx_bytes     = g_uart_tx_ring.rx_bytes;
    snap.uart_rx_overflow  = (uint16_t)g_uart_ring.overflow_drops;
    snap.uart_tx_overflow  = (uint16_t)g_uart_tx_ring.overflow_drops;
    snap.uart_ore_events   = (uint16_t)g_uart_ring.ore_events;
    snap.uart_rx_high_water = g_uart_ring.high_water;
    snap.uart_tx_high_water = g_uart_tx_ring.high_water;
    hstats_fill_health(&g_health_stats, now_ms, &snap);

    health_frame_encode(buf, &snap);

    hstats_health_generated(&g_health_stats);

    /* 发送仲裁：TX 空闲且无 A/S 待发 → 立即发；否则延迟（不丢），由
       health_flush_pending 在 TX 空闲时补发——保证 1Hz 健康帧不被普通遥测
       永久饿死。ACK/STATUS 严格最高优先级：除 txfq 已保留的重试外，还检查
       transport 中本轮新解析的 ACK/STATUS（R1：同轮竞争修复，health 启动前
       必须可见新 A/S）。 */
    {
        uint8_t ack_status_pending =
            txfq_has_retry(&g_tx_queue)
            || esp_transport_has_pending_ack()
            || esp_transport_has_pending_status();
        if (hstats_health_gate_defer(&g_health_stats,
                                     (uint8_t)(cipsend_tx_busy(&g_cipsend_tx)
                                               || !s_control_cycle_ready),
                                     ack_status_pending)) {
        if (!ESP_SendDiagFrame(buf, HEALTH_FRAME_TOTAL_LEN)) {
            hstats_health_dropped(&g_health_stats);   /* start 失败 */
        }
    } else {
        uint8_t i;
        /* 延迟：保存帧供 flush 补发。被下一帧顶替时旧帧已在 gate_defer 计 dropped。 */
        for (i = 0U; i < HEALTH_FRAME_TOTAL_LEN; i++) s_health_frame[i] = buf[i];
    }
    }
}

/* 发送仲裁：补发延迟的健康帧（TX 空闲且无 A/S 重试时）。主循环在
   ESP_SendQueuedFrames 之后调用；断连/无客户端 → 放弃待发帧。 */
static void health_flush_pending(void)
{
    if (!s_control_cycle_ready) return;
    if (!hstats_health_can_flush(&g_health_stats,
                                 cipsend_tx_busy(&g_cipsend_tx),
                                 txfq_has_retry(&g_tx_queue))) {
        return;
    }
    /* 断连/无有效客户端 → 放弃待发帧（不得发给新代次）。 */
    if (!g_tcp_client_connected || g_tcp_client_id > 4) {
        hstats_health_epoch_changed(&g_health_stats);
        return;
    }
    hstats_health_consume_due(&g_health_stats);
    if (!ESP_SendDiagFrame(s_health_frame, HEALTH_FRAME_TOTAL_LEN)) {
        hstats_health_dropped(&g_health_stats);   /* start 失败 */
    }
}

static void ESP_DrainPendingStatus(void)
{
    if (esp_transport_can_queue_status()) {
        TwinControlStatus st;
        if (twin_control_consume_pending_status(&st)) {
            esp_transport_queue_status(&st);
        }
    }
}

/* Release droppable TX only after sensor/control decisions for this loop are
   complete.  Newly-generated LINE_LOST status is materialized first, then
   ACK/STATUS are sent before health and telemetry. */
static void ESP_FlushAfterControl(void)
{
    s_control_cycle_ready = 1U;
    ESP_DrainPendingStatus();
    ESP_SendQueuedFrames(1U);
    health_flush_pending();
    ESP_TrySendImuDiagnostic();
}

int main(void)
{
    /* Health baseline: 开机最早读 RCC->CSR 复位原因位快照，随后清 RMVF，
       使下一次复位原因独立可判（IWDGRST 位可证明看门狗复位，设计 §5.4）。
       P0-1：必须用纯函数取高字节复位标志（PORRSTF bit27→0x08、IWDGRSTF
       bit29→0x20…），原 `RCC->CSR & 0x1F` 取到的是低位 LSI 状态，无法报告
       POR/IWDG。 */
    g_reset_cause = health_reset_cause_from_csr(RCC->CSR);
    RCC->CSR |= RCC_CSR_RMVF;

    Sensor_Init();
    Motor_Init();
    USART1_Init(USART1_BAUDRATE);

    /* Task 4B-4 fix: 真实单调毫秒时钟源（TIM3 1kHz），独立于主循环和
       Delay_ms()。必须在任何 mono_now_ms() 调用前初始化。 */
    mono_time_init();

    ESP_Setup();

    /* Initialise the SPSC UART RX/TX rings and enable USART1 RXNE + TXE
       interrupts.  Must happen AFTER ESP_Setup (which uses polling TX and
       blocking Delay_ms) and BEFORE the main loop (which reads the RX ring
       and pushes to the TX ring).  The RX ring is cleared first so any
       stale bytes in the USART1 DR are captured by the ISR, not mistaken
       for fresh data. */
    uart_ring_init(&g_uart_ring);
    uart_ring_init(&g_uart_tx_ring);
    USART_ITConfig(USART1, USART_IT_RXNE, ENABLE);
    NVIC_EnableIRQ(USART1_IRQn);

    /* Task 4B-4 fix: 非阻塞 CIPSEND TX 状态机初始化。 */
    cipsend_tx_init(&g_cipsend_tx);
    /* Task 4B-4 fix (Codex review remediation): 发送队列（连接代次隔离）初始化。 */
    txfq_init(&g_tx_queue);
    telemetry_batch_init(&s_tele_batch);

    /* Read identity once through hardware I2C2 before the normal software-I2C
       initialization.  This is read-only and motion-inhibited. */
    (void)MPU6050_ReadHardwareID();
    /* MPU6050 IMU */
    MPU6050_Init();
    /* yaw dt 基准：初始化为当前单调毫秒，首次 dt 由 clamp 保护。 */
    s_last_yaw_ms = mono_now_ms();

    const TwinControlParams baseline_params = {
        PID_KP, 0.0f, PID_KD, SPEED_MAX, 1U, "baseline"
    };
    TwinControlParams active_params = baseline_params;
    twin_control_init(&baseline_params);
    esp_transport_init(&g_tcp_client_connected, &g_tcp_client_id);

    /* Task 4B-4 final fix: TX connection-boundary coordinator.
       Initialised after cipsend_tx, txfq, and transport so all
       referenced modules are ready.  discard_tx_ring_cb abstracts
       the UART TX ring so the coordinator is Host-testable. */
    hstats_init(&g_health_stats);
    etc_init(&g_coordinator, &g_cipsend_tx, &g_tx_queue,
             &s_tele_batch.count, &g_health_stats,
             discard_tx_ring_cb, NULL);
    etc_set_telemetry_clear(&g_coordinator, clear_telemetry_batch_cb,
                            &s_tele_batch);

    /* Task 2B: queue the INIT/MOTION_INHIBITED status event for PC visibility. */
    {
        TwinControlStatus st;
        if (twin_control_consume_pending_status(&st)) {
            esp_transport_queue_status(&st);
        }
    }

    /* Initialise diagnostic one-shot state.  Boot starts inhibited,
       so was_inhibited = 1.  The first transition to running will
       arm the one-shot diagnostic frame. */
    diag_one_shot_init(&g_diag_state);

    float last_err = 0;
    float integral_error = 0;
    int last_dir = 1;
    int lost_step = 0;
    float sm_err = 0;
    float sm_speed = SPEED_INIT;
    float sm_turn = 0;
    uint8_t last_pattern = 0;
    uint8_t stable_pattern = 0;
    uint8_t same_count = 0;

    /* Health baseline: 安全初始化完成、电机已归零（boot 抑制态）、ESP_Setup
       阻塞延时全部结束后启用 IWDG（设计 §6.2）。 */
    iwdg_init_and_enable();

    while (1)
    {
        s_control_cycle_ready = 0U;

        /* Health baseline: 每轮迭代顶部采样（时序/喂狗基准，设计 §4.1）。 */
        health_loop_tick(mono_now_ms());

        /* Task 4B-4 final fix: three-phase ESP service.
           Phase 1 — drain RX (may detect CONNECT/CLOSED).
           Phase 2+3 — check connection boundary, then push TX.
           The coordinator ensures no old-epoch byte reaches the ESP
           after a connection boundary (see design decision §5). */
        ESP_ServiceRX();
        ESP_ServiceTX();

        /* Task 2B: detect fresh TCP CONNECT → queue authoritative state.
           The transport layer clears stale pending status on CONNECT. */
        if (g_tcp_client_connected && !g_prev_connected) {
            twin_control_queue_authoritative_status();
        }
        g_prev_connected = g_tcp_client_connected;

        esp_transport_apply_and_ack(&active_params, &baseline_params);

        /* Materialize protocol status events before any droppable TX. */
        ESP_DrainPendingStatus();

        /* R1（Codex）：1Hz 0x02 发射必须在本轮新 ACK/STATUS 物化/可见之后。
           此前 health_emit 在 ESP_ServiceRX 之前运行，新 ACK/STATUS 还在 UART
           RX 环里未被解析，health 可能抢在新 ACK/STATUS 前启动（同轮竞争漏洞）。
           现在 RX 已解析、apply_and_ack 与权威状态重发已把新 A/S 放入 transport
           pending；health_emit 内部再检查这些 pending 标志后才决定是否发射。 */
        health_emit();

        /* Before sensor/control work, service only critical ACK/STATUS. */
        ESP_SendQueuedFrames(0U);
        health_flush_pending();   /* 发送仲裁：补发延迟的健康帧（遥测让行） */

        /* Task 2B: if the controller state needs reset (new params, rollback),
           clear integral term and last error to prevent cross-candidate pollution. */
        if (twin_control_consume_controller_reset_flag()) {
            integral_error = 0.0f;
            last_err = 0.0f;
        }

        if (twin_control_motion_inhibited())
        {
            /* Reset diagnostic one-shot when motion becomes inhibited.
               Both the armed flag and the inhibition-tracking state are
               updated so a future transition to running re-arms once. */
            diag_one_shot_update(&g_diag_state, 1);
            MotorTargetsZero();
            ESP_FlushAfterControl();
            Delay_ms(LOOP_DELAY_MS);
            continue;
        }

        /* Motor motion is permitted.  Update diagnostic state to arm
           exactly once on the transition from inhibited → running. */
        diag_one_shot_update(&g_diag_state, 0);

        /* 读取IMU。Task 4B-4 fix: yaw dt 用相邻采样的真实单调时间差，
           并做边界保护（零 dt → 1ms；异常大间隔 → 100ms）。 */
        {
            uint32_t now_ms = mono_now_ms();
            uint32_t raw_dt_ms = mono_elapsed_ms(s_last_yaw_ms, now_ms);
            uint32_t dt_ms = raw_dt_ms;
            uint8_t dt_clamped = (raw_dt_ms < YAW_DT_MIN_MS ||
                                  raw_dt_ms > YAW_DT_MAX_MS) ? 1U : 0U;
            dt_ms = mono_clamp_dt_ms(dt_ms, YAW_DT_MIN_MS, YAW_DT_MAX_MS);
            s_last_yaw_ms = now_ms;
            MPU6050_SetDtClamped(dt_clamped);
            MPU6050_ReadAll();
            MPU6050_UpdateYaw((float)dt_ms / 1000.0f);
        }


        uint8_t b0 = !Sensor0_Get_State();
        uint8_t b1 = !Sensor1_Get_State();
        uint8_t b2 = !Sensor2_Get_State();
        uint8_t b3 = !Sensor3_Get_State();

        uint8_t pattern = (b0 << 3) | (b1 << 2) | (b2 << 1) | b3;
        if (pattern == last_pattern)
        {
            if (same_count < 5) same_count++;
        }
        else
        {
            same_count = 0;
            last_pattern = pattern;
        }
#if SENSOR_STABLE_COUNT == 0
        stable_pattern = pattern;
#else
        if (same_count >= SENSOR_STABLE_COUNT)
        {
            stable_pattern = pattern;
        }
#endif
        b0 = (stable_pattern >> 3) & 1;
        b1 = (stable_pattern >> 2) & 1;
        b2 = (stable_pattern >> 1) & 1;
        b3 = stable_pattern & 1;

        int black = b0 + b1 + b2 + b3;
        int pos = 0;
        if (b0) pos -= 3;
        if (b1) pos -= 1;
        if (b2) pos += 1;
        if (b3) pos += 3;

        if (black == 0)
        {
            lost_step++;

            /* Task 2B: report line-loss to protocol module.
               Task 4B-4 fix: 传入真实单调毫秒（不再依赖 g_loop_count*5ms）。
               If cumulative loss exceeds TWIN_CONTROL_LINE_LOST_MAX_MS,
               a hard stop is triggered — motors are zeroed IMMEDIATELY
               in this same iteration (no one-loop delay). */
            if (twin_control_report_line_lost(mono_now_ms())) {
                MotorTargetsZero();
                if (telemetry_rate_due(mono_now_ms(), s_last_telemetry_ms)) {
                    s_last_telemetry_ms = mono_now_ms();
                    Telemetry_Queue(0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                                    s_last_telemetry_ms,
                                    (int32_t)(mpu_data.yaw * 100),
                                    MPU6050_GetValidityFlags());
                }
                ESP_FlushAfterControl();
                Delay_ms(LOOP_DELAY_MS);
                continue;
            }

            if (lost_step < LOST_HOLD_COUNT)
            {
                MotorOut((int)sm_l, (int)sm_r);
                Diag_CaptureAndSendOnce();
            }
            else if (last_dir > 0)
            {
                MotorOut(LOST_FAST_OUTER, LOST_FAST_INNER);
                Diag_CaptureAndSendOnce();
            }
            else
            {
                MotorOut(LOST_FAST_INNER, LOST_FAST_OUTER);
                Diag_CaptureAndSendOnce();
            }

            if (telemetry_rate_due(mono_now_ms(), s_last_telemetry_ms)) {
                s_last_telemetry_ms = mono_now_ms();
                Telemetry_Queue(0, 0, 0, 0,
                                (int16_t)sm_l, (int16_t)sm_r,
                                (int16_t)sm_r, (int16_t)sm_l,
                                0, 0, s_last_telemetry_ms,
                                (int32_t)(mpu_data.yaw * 100),
                                MPU6050_GetValidityFlags());
            }

            ESP_FlushAfterControl();
            Delay_ms(LOOP_DELAY_MS);
            continue;
        }

        lost_step = 0;

        /* Task 2B: line re-acquired — reset line-loss timer. */
        twin_control_report_line_found();

        {
            float error = 0;

            if (black == 4)
            {
                error = sm_err;
            }
            else if (black == 1)
            {
                if (b0)      error = -ERR_OUTER;
                else if (b1) error = -ERR_INNER;
                else if (b2) error =  ERR_INNER;
                else if (b3) error =  ERR_OUTER;
            }
            else
            {
                error = (float)pos / black;
            }

            sm_err = sm_err * ERR_FILTER_OLD + error * ERR_FILTER_NEW;
            error = sm_err;

            float d = error - last_err;
            if (d > D_LIMIT) d = D_LIMIT;
            if (d < -D_LIMIT) d = -D_LIMIT;
            last_err = error;

            float abs_error = (error > 0) ? error : -error;
            float turn_gain = 1.0f + abs_error * TURN_GAIN_K;

            integral_error += error * ((float)LOOP_DELAY_MS / 1000.0f);
            if (integral_error > 100.0f) integral_error = 100.0f;
            if (integral_error < -100.0f) integral_error = -100.0f;
            float pid = (active_params.kp * error + active_params.ki * integral_error +
                         active_params.kd * d) * turn_gain;

            int target_speed = (int)(active_params.speed_max - abs_error * SPEED_ERR_DECAY);
            target_speed = clamp(target_speed, SPEED_MIN, active_params.speed_max);

            int target_turn = (int)pid;
            target_turn = clamp(target_turn, -TURN_LIMIT, TURN_LIMIT);

            sm_speed = sm_speed * SPEED_FILTER_OLD + target_speed * SPEED_FILTER_NEW;
            sm_turn  = sm_turn  * TURN_FILTER_OLD + target_turn  * TURN_FILTER_NEW;

            int speed = (int)sm_speed;
            int turn  = (int)sm_turn;
            int curve_reverse = 0;

            switch (stable_pattern)
            {
                case PATTERN_LEFT_OUTER:
                case PATTERN_LEFT_HEAVY:
                {
                    int force_turn;
                    curve_reverse = 1;
                    speed = clamp(SPEED_MIN, SPEED_MIN, active_params.speed_max);
                    force_turn = speed - CURVE_INNER_REVERSE + CURVE_MIN_TURN_EXTRA;
                    turn = -force_turn;
                    break;
                }
                case PATTERN_LEFT_INNER:
                {
                    int force_turn;
                    curve_reverse = 1;
                    speed = clamp(SPEED_MIN, SPEED_MIN, active_params.speed_max);
                    force_turn = speed - CURVE_MID_INNER_REVERSE + CURVE_MID_TURN_EXTRA;
                    turn = -force_turn;
                    break;
                }
                case PATTERN_RIGHT_INNER:
                {
                    int force_turn;
                    curve_reverse = 1;
                    speed = clamp(SPEED_MIN, SPEED_MIN, active_params.speed_max);
                    force_turn = speed - CURVE_MID_INNER_REVERSE + CURVE_MID_TURN_EXTRA;
                    turn = force_turn;
                    break;
                }
                case PATTERN_RIGHT_HEAVY:
                case PATTERN_RIGHT_OUTER:
                {
                    int force_turn;
                    curve_reverse = 1;
                    speed = clamp(SPEED_MIN, SPEED_MIN, active_params.speed_max);
                    force_turn = speed - CURVE_INNER_REVERSE + CURVE_MIN_TURN_EXTRA;
                    turn = force_turn;
                    break;
                }
                default:
                    break;
            }

            int left  = speed + turn;
            int right = speed - turn;

            if (curve_reverse)
            {
                left  = clamp(left,  CURVE_INNER_REVERSE, MOTOR_LIMIT);
                right = clamp(right, CURVE_INNER_REVERSE, MOTOR_LIMIT);
            }
            else
            {
                left  = clamp(left,  20, MOTOR_LIMIT);
                right = clamp(right, 20, MOTOR_LIMIT);
            }

            if (pos != 0)
                last_dir = (pos > 0) ? 1 : -1;

            MotorOut(left, right);
            Diag_CaptureAndSendOnce();

            if (telemetry_rate_due(mono_now_ms(), s_last_telemetry_ms)) {
                s_last_telemetry_ms = mono_now_ms();
                Telemetry_Queue(b0, b1, b2, b3,
                                (int16_t)sm_l, (int16_t)sm_r,
                                (int16_t)sm_r, (int16_t)sm_l,
                                 (int16_t)(error * 100), (int16_t)pid,
                                 s_last_telemetry_ms,
                                 (int32_t)(mpu_data.yaw * 100),
                                 MPU6050_GetValidityFlags());
            }
        }

        ESP_FlushAfterControl();
        Delay_ms(LOOP_DELAY_MS);
    }
}
