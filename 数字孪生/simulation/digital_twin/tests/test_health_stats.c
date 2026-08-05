/* Host C test for health_stats: main-loop timing + CIPSEND/telemetry/health
 * counters (firmware health baseline, Task 2).
 *
 * TDD (strict):
 *   - RED:  health_stats.h/.c absent -> cl cannot open source file, non-zero exit.
 *   - GREEN: all assertions below hold; exit 0.
 *
 * Covers (plan Task 2 Step 2.1 items 1..6):
 *   1. hstats_loop_tick seq/gap/max incl. uint32 wrap; gap saturates to u16.
 *   2. tx_started/tx_terminal result classification + duration + peak.
 *   3. tx_started start_ms -> terminal duration; cipsend_max_duration_ms peak.
 *   4. hstats_fill_health maps fields into HealthSnapshot; snapshot_tick_ms==now.
 *   5. health_* six counters, TAG_DIAG_HEALTH exclusive (no mixing with TAG_DIAG).
 *   6. Round 3 item 3: five transitions with identities
 *        generated==dropped+started, started==ok+failed+in_flight (in_flight in {0,1});
 *      plus mod-2^16 identity across u16 wrap.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "health_stats.h"
#include "health_frame.h"
#include "cipsend_tx.h"
#include "cipsend_transaction.h"

#define CHECK(expression) do { \
    if (!(expression)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expression); \
        return 1; \
    } \
} while (0)

/* ---- item 1: loop tick seq/gap/max + wrap ----
   P0-2: first tick only establishes the time baseline.  seq counts 1 per
   design, but gap/max stay 0 so the ESP_Setup boot delay (mono started
   before the first main-loop tick) is never recorded as a loop gap. */
static int test_loop_tick_seq_gap_max(void)
{
    HealthStats s;
    hstats_init(&s);
    CHECK(s.loop_seq == 0U);

    hstats_loop_tick(&s, 12000U);         /* first tick = baseline only */
    CHECK(s.loop_seq == 1U);
    CHECK(s.loop_last_gap_ms == 0U);
    CHECK(s.loop_max_gap_ms == 0U);

    hstats_loop_tick(&s, 12005U);         /* seq=2, gap=5 */
    CHECK(s.loop_seq == 2U);
    CHECK(s.loop_last_gap_ms == 5U);
    CHECK(s.loop_max_gap_ms == 5U);

    hstats_loop_tick(&s, 12505U);         /* gap=500 */
    CHECK(s.loop_last_gap_ms == 500U);
    CHECK(s.loop_max_gap_ms == 500U);

    hstats_loop_tick(&s, 13505U);         /* gap=1000 == peak */
    CHECK(s.loop_last_gap_ms == 1000U);
    CHECK(s.loop_max_gap_ms == 1000U);

    hstats_loop_tick(&s, 14605U);         /* gap=1100 > peak */
    CHECK(s.loop_last_gap_ms == 1100U);
    CHECK(s.loop_max_gap_ms == 1100U);

    /* uint32 wrap: 0xFFFFFFFF -> 0x00000005, wrap-safe gap = 6
       (0x00000005 - 0xFFFFFFFF mod 2^32 = 6) */
    hstats_loop_tick(&s, 0xFFFFFFFFU);
    CHECK(s.loop_max_gap_ms == 0xFFFFU);  /* huge gap saturates the peak */
    hstats_loop_tick(&s, 0x00000005U);
    CHECK(s.loop_last_gap_ms == 6U);
    return 0;
}

/* ---- item 1: loop gap saturates to u16 in snapshot ---- */
static int test_loop_gap_saturates_in_snapshot(void)
{
    HealthStats s;
    HealthSnapshot snap;
    hstats_init(&s);
    s.loop_last_gap_ms = 70000U;   /* > 0xFFFF */
    s.loop_max_gap_ms  = 80000U;
    memset(&snap, 0, sizeof(snap));
    hstats_fill_health(&s, 42U, &snap);
    CHECK(snap.snapshot_tick_ms == 42U);
    CHECK(snap.loop_last_gap_ms == 0xFFFFU);
    CHECK(snap.loop_max_gap_ms == 0xFFFFU);
    return 0;
}

/* ---- item 2/3: tx_started / tx_terminal classification + duration ---- */
static int test_tx_classification_and_duration(void)
{
    HealthStats s;
    hstats_init(&s);

    /* TELEMETRY start -> telemetry_started + telemetry_tx_started + cipsend_started */
    hstats_tx_started(&s, CIPSEND_TX_TAG_TELEMETRY, 100U);
    CHECK(s.telemetry_started == 1U);
    CHECK(s.telemetry_tx_started == 1U);
    CHECK(s.cipsend_started == 1U);

    /* OK terminal */
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_TELEMETRY, CTS_RESULT_OK, 0U, 1U, 150U);
    CHECK(s.telemetry_tx_ok == 1U);
    CHECK(s.telemetry_tx_failed == 0U);
    CHECK(s.cipsend_completed == 1U);
    CHECK(s.cipsend_ok == 1U);
    CHECK(s.cipsend_last_duration_ms == 50U);
    CHECK(s.cipsend_max_duration_ms == 50U);

    /* ERROR terminal */
    hstats_tx_started(&s, CIPSEND_TX_TAG_TELEMETRY, 200U);
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_TELEMETRY, CTS_RESULT_ERROR, 0U, 1U, 210U);
    CHECK(s.cipsend_error == 1U);
    CHECK(s.telemetry_tx_failed == 1U);
    CHECK(s.cipsend_max_duration_ms == 50U);   /* 10 < 50, peak unchanged */

    /* PROMPT_TIMEOUT: result NONE + timeout_aborted=1 + entered_send_data=0 */
    hstats_tx_started(&s, CIPSEND_TX_TAG_TELEMETRY, 300U);
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_TELEMETRY, CTS_RESULT_NONE, 1U, 0U, 400U);
    CHECK(s.cipsend_prompt_timeout == 1U);
    CHECK(s.cipsend_sendok_timeout == 0U);
    CHECK(s.cipsend_max_duration_ms == 100U);  /* 400-300=100 > 50 */

    /* SENDOK_TIMEOUT: result NONE + timeout_aborted=1 + entered_send_data=1 */
    hstats_tx_started(&s, CIPSEND_TX_TAG_TELEMETRY, 500U);
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_TELEMETRY, CTS_RESULT_NONE, 1U, 1U, 700U);
    CHECK(s.cipsend_sendok_timeout == 1U);
    CHECK(s.cipsend_prompt_timeout == 1U);    /* unchanged */
    CHECK(s.cipsend_max_duration_ms == 200U); /* 700-500=200 > 100 */

    /* CLOSED terminal */
    hstats_tx_started(&s, CIPSEND_TX_TAG_TELEMETRY, 800U);
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_TELEMETRY, CTS_RESULT_CLOSED, 0U, 1U, 850U);
    CHECK(s.cipsend_closed == 1U);
    CHECK(s.cipsend_max_duration_ms == 200U); /* 50 < 200, peak unchanged */

    /* completed == ok+error+prompt+sendok+closed (5 completed so far) */
    CHECK(s.cipsend_completed == 5U);
    CHECK(s.cipsend_ok + s.cipsend_error + s.cipsend_prompt_timeout +
          s.cipsend_sendok_timeout + s.cipsend_closed == 5U);

    /* non-timeout NONE (no timeout_aborted) is NOT classified as a timeout */
    hstats_tx_started(&s, CIPSEND_TX_TAG_TELEMETRY, 900U);
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_TELEMETRY, CTS_RESULT_NONE, 0U, 1U, 901U);
    CHECK(s.cipsend_prompt_timeout == 1U);
    CHECK(s.cipsend_sendok_timeout == 1U);
    return 0;
}

/* ---- item 4: fill_health maps fields + tick ---- */
static int test_fill_health_maps_fields(void)
{
    HealthStats s;
    HealthSnapshot snap;
    hstats_init(&s);

    /* Golden-value spot check: set stats to the golden snapshot's stats-owned
       fields and verify the snapshot reproduces them. */
    s.loop_seq               = 123456U;
    s.loop_last_gap_ms       = 6U;
    s.loop_max_gap_ms        = 500U;
    s.telemetry_generated    = 100U;
    s.telemetry_overwritten  = 5U;
    s.telemetry_tx_started   = 95U;
    s.telemetry_tx_ok        = 90U;
    s.telemetry_tx_failed    = 5U;
    s.cipsend_started        = 110U;
    s.cipsend_completed      = 105U;
    s.cipsend_ok             = 100U;
    s.cipsend_error          = 1U;
    s.cipsend_prompt_timeout = 2U;
    s.cipsend_sendok_timeout = 1U;
    s.cipsend_closed         = 1U;
    s.cipsend_last_duration_ms = 100U;
    s.cipsend_max_duration_ms  = 500U;
    s.ack_started            = 5U;
    s.status_started         = 4U;
    s.telemetry_started      = 95U;
    s.diag_health_started    = 2U;
    s.status_retry           = 2U;
    s.ack_retry              = 1U;
    s.boundary_aborts        = 0U;
    s.health_generated       = 12U;
    s.health_dropped         = 2U;
    s.health_started         = 10U;
    s.health_ok              = 9U;
    s.health_failed          = 1U;
    s.health_last_duration_ms = 45U;

    memset(&snap, 0, sizeof(snap));
    hstats_fill_health(&s, 1000000U, &snap);
    CHECK(snap.snapshot_tick_ms == 1000000U);
    CHECK(snap.loop_seq == 123456U);
    CHECK(snap.loop_last_gap_ms == 6U);
    CHECK(snap.loop_max_gap_ms == 500U);
    CHECK(snap.telemetry_generated == 100U);
    CHECK(snap.telemetry_overwritten == 5U);
    CHECK(snap.telemetry_tx_started == 95U);
    CHECK(snap.telemetry_tx_ok == 90U);
    CHECK(snap.telemetry_tx_failed == 5U);
    CHECK(snap.cipsend_started == 110U);
    CHECK(snap.cipsend_completed == 105U);
    CHECK(snap.cipsend_ok == 100U);
    CHECK(snap.cipsend_error == 1U);
    CHECK(snap.cipsend_prompt_timeout == 2U);
    CHECK(snap.cipsend_sendok_timeout == 1U);
    CHECK(snap.cipsend_closed == 1U);
    CHECK(snap.cipsend_last_duration_ms == 100U);
    CHECK(snap.cipsend_max_duration_ms == 500U);
    CHECK(snap.ack_started == 5U);
    CHECK(snap.status_started == 4U);
    CHECK(snap.telemetry_started == 95U);
    CHECK(snap.diag_health_started == 2U);
    CHECK(snap.status_retry == 2U);
    CHECK(snap.ack_retry == 1U);
    CHECK(snap.boundary_aborts == 0U);
    CHECK(snap.health_generated == 12U);
    CHECK(snap.health_dropped == 2U);
    CHECK(snap.health_started == 10U);
    CHECK(snap.health_ok == 9U);
    CHECK(snap.health_failed == 1U);
    CHECK(snap.health_last_duration_ms == 45U);
    return 0;
}

/* ---- item 5: health_* six counters, TAG_DIAG_HEALTH exclusive ---- */
static int test_health_counters_no_mixing(void)
{
    HealthStats s;
    hstats_init(&s);

    hstats_health_generated(&s);
    CHECK(s.health_generated == 1U);
    hstats_health_dropped(&s);
    CHECK(s.health_dropped == 1U);

    /* TAG_DIAG_HEALTH start -> health_started++, NOT diag_health_started */
    hstats_tx_started(&s, CIPSEND_TX_TAG_DIAG_HEALTH, 1000U);
    CHECK(s.health_started == 1U);
    CHECK(s.diag_health_started == 0U);

    /* OK terminal -> health_ok++ + last_duration */
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_DIAG_HEALTH, CTS_RESULT_OK, 0U, 1U, 1045U);
    CHECK(s.health_ok == 1U);
    CHECK(s.health_failed == 0U);
    CHECK(s.health_last_duration_ms == 45U);

    /* non-OK terminal -> health_failed++ */
    hstats_tx_started(&s, CIPSEND_TX_TAG_DIAG_HEALTH, 2000U);
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_DIAG_HEALTH, CTS_RESULT_ERROR, 0U, 1U, 2100U);
    CHECK(s.health_failed == 1U);
    CHECK(s.health_ok == 1U);

    /* TAG_DIAG (0x7E) only increments diag_health_started; health_* unchanged */
    hstats_tx_started(&s, CIPSEND_TX_TAG_DIAG, 3000U);
    CHECK(s.diag_health_started == 1U);
    CHECK(s.health_started == 2U);   /* two DIAG_HEALTH transactions started */
    CHECK(s.health_ok == 1U);
    CHECK(s.health_failed == 1U);
    return 0;
}

/* ---- item 6: Round 3 five transitions + identities ---- */
static int test_round3_five_transitions(void)
{
    HealthStats s;
    HealthSnapshot snap;
    hstats_init(&s);

    /* ① busy-drop: generated+1, dropped+1, identity holds (in_flight=0). */
    hstats_health_generated(&s);
    hstats_health_dropped(&s);
    CHECK(s.health_generated == s.health_dropped + s.health_started);
    CHECK(s.health_started == s.health_ok + s.health_failed + 0U);

    /* ② start-fail: fill snapshot (pre-classification counts), generated+1,
          start fails -> dropped+1, identity restored. */
    memset(&snap, 0, sizeof(snap));
    hstats_fill_health(&s, 1000U, &snap);
    CHECK(snap.health_generated == 1U);       /* pre-classification value */
    CHECK(snap.health_dropped == 1U);
    hstats_health_generated(&s);
    hstats_health_dropped(&s);                 /* start failure */
    CHECK(s.health_generated == s.health_dropped + s.health_started);
    CHECK(s.health_started == s.health_ok + s.health_failed + 0U);

    /* ③ start-success in-flight: fill snapshot, generated+1, start ok -> started+1,
          in_flight=1, started==ok+failed+1. */
    memset(&snap, 0, sizeof(snap));
    hstats_fill_health(&s, 2000U, &snap);
    CHECK(snap.health_generated == 2U);   /* pre-classification: ①+② = 2 */
    hstats_health_generated(&s);
    hstats_tx_started(&s, CIPSEND_TX_TAG_DIAG_HEALTH, 2000U);
    CHECK(s.health_generated == s.health_dropped + s.health_started);
    CHECK(s.health_started == s.health_ok + s.health_failed + 1U);  /* in_flight=1 */

    /* ④ terminal-ok: ok+1, in_flight back to 0. */
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_DIAG_HEALTH, CTS_RESULT_OK, 0U, 1U, 2100U);
    CHECK(s.health_ok == 1U);
    CHECK(s.health_started == s.health_ok + s.health_failed + 0U);  /* in_flight=0 */

    /* ⑤ terminal-fail: fill snapshot, generated+1, start ok, non-OK terminal
          -> failed+1, in_flight back to 0. */
    memset(&snap, 0, sizeof(snap));
    hstats_fill_health(&s, 3000U, &snap);
    hstats_health_generated(&s);
    hstats_tx_started(&s, CIPSEND_TX_TAG_DIAG_HEALTH, 3000U);
    CHECK(s.health_started == s.health_ok + s.health_failed + 1U);
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_DIAG_HEALTH, CTS_RESULT_CLOSED, 0U, 1U, 3050U);
    CHECK(s.health_failed == 1U);
    CHECK(s.health_started == s.health_ok + s.health_failed + 0U);

    /* final identity after all five transitions */
    CHECK(s.health_generated == s.health_dropped + s.health_started);
    return 0;
}

/* ---- item 6: mod-2^16 identity across u16 wrap ---- */
static int test_round3_wrap_identity(void)
{
    HealthStats s;
    hstats_init(&s);

    /* Pre-wrap valid state: generated=0xFFFF, dropped=0x7FFF, started=0x8000,
       ok=0x7FFF, failed=1 -> started==ok+failed (in_flight=0). */
    s.health_generated = 0xFFFFU;
    s.health_dropped   = 0x7FFFU;
    s.health_started   = 0x8000U;
    s.health_ok        = 0x7FFFU;
    s.health_failed    = 1U;
    CHECK((s.health_started & 0xFFFFU) == ((s.health_ok + s.health_failed) & 0xFFFFU));

    /* ③ start-success in-flight across wrap. */
    hstats_health_generated(&s);                 /* 0x10000 -> u16 0 */
    hstats_tx_started(&s, CIPSEND_TX_TAG_DIAG_HEALTH, 1000U);  /* started 0x8001 */
    CHECK((s.health_generated & 0xFFFFU) == ((s.health_dropped + s.health_started) & 0xFFFFU));
    CHECK((s.health_started & 0xFFFFU) == ((s.health_ok + s.health_failed + 1U) & 0xFFFFU));

    /* ④ terminal-ok across wrap. */
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_DIAG_HEALTH, CTS_RESULT_OK, 0U, 1U, 1100U); /* ok 0x8000 */
    CHECK((s.health_generated & 0xFFFFU) == ((s.health_dropped + s.health_started) & 0xFFFFU));
    CHECK((s.health_started & 0xFFFFU) == ((s.health_ok + s.health_failed) & 0xFFFFU));

    /* ② start-fail across wrap. */
    hstats_health_generated(&s);                 /* 0x10001 -> u16 1 */
    hstats_health_dropped(&s);                   /* dropped 0x8000 */
    CHECK((s.health_generated & 0xFFFFU) == ((s.health_dropped + s.health_started) & 0xFFFFU));
    return 0;
}

/* ---- 发送仲裁：健康帧不被遥测饿死（CURRENT_STATUS 下一步）----
   RED：hstats_health_gate_defer / can_flush / consume_due / epoch_changed /
   health_due 尚不存在 → cl 编译失败，非零退出（与初始 Task 2 RED 同模式）。
   新恒等式：generated == dropped + started + due（due∈{0,1}，延迟未发送帧）。 */
static int test_health_arbitration(void)
{
    HealthStats s;
    uint32_t gen_before, drop_before;

    hstats_init(&s);

    /* ① TX 忙 → 延迟（不丢）：generated+1, due=1, dropped 不变,
          identity generated == dropped + started + due。 */
    hstats_health_generated(&s);
    CHECK(hstats_health_gate_defer(&s, 1U, 0U) == 0U);   /* busy → defer */
    CHECK(s.health_due == 1U);
    CHECK(s.health_dropped == 0U);
    CHECK(s.health_generated == s.health_dropped + s.health_started + s.health_due);
    CHECK(hstats_health_due(&s) == 1U);

    /* ② 再次 1Hz fire（仍忙/有重试）→ 旧待发帧被顶替：dropped+1, due 仍 1。 */
    gen_before = s.health_generated;
    drop_before = s.health_dropped;
    hstats_health_generated(&s);
    CHECK(hstats_health_gate_defer(&s, 1U, 1U) == 0U);   /* busy + retry → defer */
    CHECK(s.health_generated == gen_before + 1U);
    CHECK(s.health_dropped == drop_before + 1U);
    CHECK(s.health_due == 1U);
    CHECK(s.health_generated == s.health_dropped + s.health_started + s.health_due);

    /* ③ TX 空闲 → can_flush=1，consume 后发送（started+1 via hstats_tx_started），
          identity 恢复（due=0）。 */
    CHECK(hstats_health_can_flush(&s, 0U, 0U) == 1U);
    hstats_health_consume_due(&s);
    CHECK(s.health_due == 0U);
    hstats_tx_started(&s, CIPSEND_TX_TAG_DIAG_HEALTH, 1000U);
    CHECK(s.health_generated == s.health_dropped + s.health_started + 0U);
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_DIAG_HEALTH, CTS_RESULT_OK, 0U, 1U, 1050U);
    CHECK(s.health_ok == 1U);
    CHECK(s.health_started == s.health_ok + s.health_failed + 0U);

    /* ④ flush 但 start 失败 → dropped+1。 */
    hstats_health_generated(&s);
    CHECK(hstats_health_gate_defer(&s, 1U, 0U) == 0U);   /* busy → defer */
    CHECK(hstats_health_can_flush(&s, 0U, 0U) == 1U);
    hstats_health_consume_due(&s);
    hstats_health_dropped(&s);                            /* start 失败 */
    CHECK(s.health_generated == s.health_dropped + s.health_started + 0U);

    /* ⑤ epoch 变化 → 放弃待发帧（dropped+1, due=0）。 */
    hstats_health_generated(&s);
    CHECK(hstats_health_gate_defer(&s, 1U, 0U) == 0U);   /* busy → defer */
    hstats_health_epoch_changed(&s);
    CHECK(s.health_due == 0U);
    CHECK(s.health_generated == s.health_dropped + s.health_started + 0U);

    /* ⑥ TX 空闲 → 立即发送（gate 返回 1，due 不变 0）。 */
    hstats_health_generated(&s);
    CHECK(hstats_health_gate_defer(&s, 0U, 0U) == 1U);
    CHECK(s.health_due == 0U);
    hstats_tx_started(&s, CIPSEND_TX_TAG_DIAG_HEALTH, 2000U);
    CHECK(s.health_generated == s.health_dropped + s.health_started + 0U);
    return 0;
}

/* R1（Codex）：同轮竞争——TX 空闲但 ACK/STATUS 待发（transport pending 或
   txfq 已保留）→ health 必须延迟，不得抢先启动。 */
static int test_health_arbitration_ack_priority(void)
{
    HealthStats s;
    hstats_init(&s);

    /* TX 空闲 + A/S 待发 → gate 返回 0（延迟），due=1，恒等式含 due。 */
    hstats_health_generated(&s);
    CHECK(hstats_health_gate_defer(&s, 0U, 1U) == 0U);   /* TX free, A/S pending */
    CHECK(s.health_due == 1U);
    CHECK(s.health_dropped == 0U);
    CHECK(s.health_generated == s.health_dropped + s.health_started + s.health_due);

    /* 延迟后 flush（A/S 已清）→ 发送成功，恒等式恢复（due=0）。 */
    CHECK(hstats_health_can_flush(&s, 0U, 0U) == 1U);
    hstats_health_consume_due(&s);
    hstats_tx_started(&s, CIPSEND_TX_TAG_DIAG_HEALTH, 1000U);
    CHECK(s.health_generated == s.health_dropped + s.health_started + 0U);
    hstats_tx_terminal(&s, CIPSEND_TX_TAG_DIAG_HEALTH, CTS_RESULT_OK, 0U, 1U, 1045U);
    CHECK(s.health_started == s.health_ok + s.health_failed + 0U);
    return 0;
}

/* 无 due 时 epoch 变化是 no-op；can_flush 在 due=0 时为 0。 */
static int test_health_arbitration_noop(void)
{
    HealthStats s;
    hstats_init(&s);
    CHECK(hstats_health_can_flush(&s, 0U, 0U) == 0U);
    CHECK(hstats_health_due(&s) == 0U);
    hstats_health_epoch_changed(&s);   /* 无待发帧 → 无副作用 */
    CHECK(s.health_dropped == 0U);
    CHECK(s.health_due == 0U);
    return 0;
}

static int run_all_tests(void)
{
    if (test_loop_tick_seq_gap_max()) return 1;
    if (test_loop_gap_saturates_in_snapshot()) return 1;
    if (test_tx_classification_and_duration()) return 1;
    if (test_fill_health_maps_fields()) return 1;
    if (test_health_counters_no_mixing()) return 1;
    if (test_round3_five_transitions()) return 1;
    if (test_round3_wrap_identity()) return 1;
    if (test_health_arbitration()) return 1;
    if (test_health_arbitration_noop()) return 1;
    if (test_health_arbitration_ack_priority()) return 1;
    puts("PASS test_health_stats");
    return 0;
}

int main(void)
{
    return run_all_tests();
}
