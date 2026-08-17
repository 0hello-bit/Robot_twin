#ifndef CIPSEND_TX_H
#define CIPSEND_TX_H

#include <stdint.h>
#include "cipsend_transaction.h"

/* ── Task 4B-4 fix: 非阻塞但严格串行的 CIPSEND TX 状态机 ──────────────
 *
 * 背景：旧 `ESP_DoCIPSENDTransaction()` 在主循环里同步轮询 '>' 与
 * `SEND OK`（每帧 Delay_ms(1)），遥测每帧阻塞主循环 ~110ms，导致
 * tick 不按真实时间推进（review 事实 #1/#2）。
 *
 * 本模块把阻塞 while 改为持久化非阻塞 TX 状态机：
 *   - 同一时间只允许一个 AT+CIPSEND 事务；上一事务终态前绝不开始下一事务。
 *   - 每次主循环只 service 一小步（cipsend_tx_tick），不阻塞控制循环。
 *   - 所有 UART RX 字节必须同时交给 cipsend_tx_feed_byte()（本模块解析
 *     '>' / SEND OK / ERROR / busy / CLOSED）和传输层 CONNECT/CLOSED/+IPD
 *     路径（调用方在 feed 前后自行路由）。
 *   - 完成语义完整保留：SEND OK 成功、ERROR/busy/CLOSED 失败、超时失败。
 *   - 纯 C、无动态内存、ARMCC5 兼容；时间由调用方以 now_ms 传入（可 Host 测试）。
 */

/* ── 缓冲区尺寸 ─────────────────────────────────────────────────────── */
#define CIPSEND_TX_MAX_CMD   24U          /* "AT+CIPSEND=<id>,<len>\r\n"     */
#define CIPSEND_TX_MAX_DATA  248U         /* ESP CIPSEND data ceiling         */

/* ── 优先级 / 标签 ───────────────────────────────────────────────────── */
#define CIPSEND_TX_PRIORITY_DROPPABLE  0U  /* telemetry / diag               */
#define CIPSEND_TX_PRIORITY_CRITICAL   1U  /* ACK / STATUS，可靠重试         */

#define CIPSEND_TX_TAG_NONE       0U
#define CIPSEND_TX_TAG_ACK        1U
#define CIPSEND_TX_TAG_STATUS     2U
#define CIPSEND_TX_TAG_TELEMETRY  3U
#define CIPSEND_TX_TAG_DIAG       4U
#define CIPSEND_TX_TAG_IMU_DIAGNOSTIC 6U
#define CIPSEND_TX_TAG_CLOCK_SYNC 7U

/* ── 状态 ────────────────────────────────────────────────────────────── */
#define CIPSEND_TX_STATE_IDLE          0U  /* 无事务                          */
#define CIPSEND_TX_STATE_SEND_CMD      1U  /* 发送 AT+CIPSEND 命令            */
#define CIPSEND_TX_STATE_WAIT_PROMPT   2U  /* 等 '>'                          */
#define CIPSEND_TX_STATE_SEND_DATA     3U  /* 发送载荷                        */
#define CIPSEND_TX_STATE_WAIT_SENDOK   4U  /* 等 SEND OK / ERROR / CLOSED     */
#define CIPSEND_TX_STATE_COMPLETE      5U  /* SEND OK 确认                    */
#define CIPSEND_TX_STATE_FAILED        6U  /* ERROR/busy/CLOSED/超时          */

/* ── 超时（与旧 main.c 常量一致） ────────────────────────────────────── */
#define CIPSEND_TX_PROMPT_TIMEOUT_MS  200U
#define CIPSEND_TX_SENDOK_TIMEOUT_MS  500U

/* 字节 sink：发送一个字节。返回 1 表示接受，0 表示暂不能接受（下轮重试）。
 * 固件实现为压入 UART TX ring（非阻塞）；Host 测试实现为记录。 */
typedef uint8_t (*CipsendTxByteSink)(void *ctx, uint8_t byte);

typedef uint8_t (*CipsendTxDataReadyFn)(uint8_t *data, uint16_t *data_len,
                                        uint16_t capacity, uint32_t now_ms,
                                        void *ctx);

typedef struct {
    char     cmd[CIPSEND_TX_MAX_CMD];   /* AT+CIPSEND=id,len\r\n             */
    uint16_t cmd_len;
    uint16_t cmd_pos;
    uint8_t  data[CIPSEND_TX_MAX_DATA]; /* 载荷字节                          */
    uint16_t data_len;
    uint16_t data_pos;
    uint8_t  state;
    uint8_t  priority;                  /* CIPSEND_TX_PRIORITY_*            */
    uint8_t  tag;                       /* CIPSEND_TX_TAG_*                 */
    uint8_t  result;                    /* 终态结果（CTS_RESULT_*）          */
    uint8_t  timeout_abort;             /* 1 = 因超时失败（无终端行）        */
    uint8_t  deadline_stale;            /* 1 = 进入新阶段后首次 tick 需刷新   */
    CipsendTransaction cts;             /* '>' / SEND OK / ERROR / CLOSED    */
    uint32_t deadline_ms;               /* 当前阶段绝对截止（mono ms）       */
    CipsendTxDataReadyFn data_ready_fn;
    void    *data_ready_ctx;
    uint8_t  data_ready_called;
} CipsendTx;

/* 初始化（置 IDLE）。开机调用一次。 */
void cipsend_tx_init(CipsendTx *tx);

/* 开始新事务。仅当 state == IDLE 时成功；忙碌或终态未 reset 返回 0。
 * cmd: "AT+CIPSEND=<id>,<len>\r\n"（含 \r\n）。
 * data: 载荷字节；data_len 为载荷长度。
 * now_ms: 当前单调毫秒（用于超时）。 */
uint8_t cipsend_tx_start(CipsendTx *tx,
                         const char *cmd, uint16_t cmd_len,
                         const uint8_t *data, uint16_t data_len,
                         uint8_t priority, uint8_t tag,
                         uint32_t now_ms);

uint8_t cipsend_tx_start_late_data(
    CipsendTx *tx, const char *cmd, uint16_t cmd_len, uint16_t data_len,
    uint8_t priority, uint8_t tag, uint32_t now_ms,
    CipsendTxDataReadyFn data_ready_fn, void *data_ready_ctx);

/* 是否有事务在推进（非 IDLE 且非终态）。 */
uint8_t cipsend_tx_busy(const CipsendTx *tx);

/* 喂一个 UART RX 字节。调用方必须对每个 RX 字节同时调用本函数和
 * 传输层 esp_transport_process_byte()（CONNECT/CLOSED/+IPD 路由）。 */
void cipsend_tx_feed_byte(CipsendTx *tx, uint8_t byte);

/* 推进状态机（每次主循环调用一次）：发送待发字节、检查超时。
 * sink 用于发送命令/载荷字节；sink_ctx 为调用方上下文。 */
void cipsend_tx_tick(CipsendTx *tx, uint32_t now_ms,
                     CipsendTxByteSink sink, void *sink_ctx);

/* 是否到达终态（COMPLETE 或 FAILED）。 */
uint8_t cipsend_tx_is_terminal(const CipsendTx *tx);

/* 终态结果：CTS_RESULT_OK / ERROR / CLOSED；超时为 CTS_RESULT_NONE。
 * 仅在 cipsend_tx_is_terminal() 为真时有效。 */
uint8_t cipsend_tx_result(const CipsendTx *tx);

/* 当前事务标签（用于调用方清对应重试缓冲）。 */
uint8_t cipsend_tx_tag(const CipsendTx *tx);

/* 是否为超时失败（无终端响应行）。 */
uint8_t cipsend_tx_timeout_aborted(const CipsendTx *tx);

/* 回到 IDLE。调用方在读取终态结果后调用，允许下一个事务开始。 */
void cipsend_tx_reset(CipsendTx *tx);

/* 内部：在 SEND_CMD / SEND_DATA 状态尝试通过 sink 发送剩余字节。
 * 返回是否全部发送完成。 */
uint8_t cipsend_tx_send_pending(CipsendTx *tx,
                                CipsendTxByteSink sink, void *sink_ctx);

#endif /* CIPSEND_TX_H */
