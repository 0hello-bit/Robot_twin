/******************************************************************************
 * Host-side tests for the SPSC UART RX ring buffer (uart_ring).
 *
 * Compile with MSVC:
 *   cl /nologo /TC /W4 /WX /utf-8 /D_CRT_SECURE_NO_WARNINGS
 *       test_uart_ring.c uart_ring.c
 *       /Fetest_uart_ring.exe
 *
 * Run:
 *   test_uart_ring.exe
 ******************************************************************************/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "uart_ring.h"

/* Test assertion macro — return 1 on failure. */
#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

/* ======================================================================
 * Test: push three bytes, pop verifies FIFO order
 * ====================================================================== */
static int test_push_pop_fifo_order(void)
{
    UartRing ring;
    uart_ring_init(&ring);

    CHECK(uart_ring_push(&ring, 0xAA));
    CHECK(uart_ring_push(&ring, 0xBB));
    CHECK(uart_ring_push(&ring, 0xCC));

    uint8_t b;
    CHECK(uart_ring_pop(&ring, &b));  CHECK(b == 0xAA);
    CHECK(uart_ring_pop(&ring, &b));  CHECK(b == 0xBB);
    CHECK(uart_ring_pop(&ring, &b));  CHECK(b == 0xCC);

    /* Ring should be empty now */
    CHECK(!uart_ring_pop(&ring, &b));
    return 0;
}

/* ======================================================================
 * Test: wraparound — fill ring to near capacity, then push enough to
 * wrap the producer index.
 * ====================================================================== */
static int test_wraparound(void)
{
    UartRing ring;
    uart_ring_init(&ring);

    /* Fill with bytes 0..UART_RING_SIZE-1 */
    unsigned i;
    for (i = 0U; i < UART_RING_SIZE; i++) {
        CHECK(uart_ring_push(&ring, (uint8_t)(i & 0xFF)));
    }

    /* Pop half */
    uint8_t b;
    for (i = 0U; i < UART_RING_SIZE / 2U; i++) {
        CHECK(uart_ring_pop(&ring, &b));
        CHECK(b == (uint8_t)(i & 0xFF));
    }

    /* Push more bytes to force producer wraparound */
    for (i = 0U; i < UART_RING_SIZE / 2U; i++) {
        CHECK(uart_ring_push(&ring, (uint8_t)(0x80U | (i & 0x7FU))));
    }

    /* Read remaining — should be second half of original, then new bytes */
    for (i = UART_RING_SIZE / 2U; i < UART_RING_SIZE; i++) {
        CHECK(uart_ring_pop(&ring, &b));
        CHECK(b == (uint8_t)(i & 0xFF));
    }
    for (i = 0U; i < UART_RING_SIZE / 2U; i++) {
        CHECK(uart_ring_pop(&ring, &b));
        CHECK(b == (uint8_t)(0x80U | (i & 0x7FU)));
    }

    CHECK(!uart_ring_pop(&ring, &b));
    return 0;
}

/* ======================================================================
 * Test: full buffer correctly drops bytes and increments overflow counter.
 * ====================================================================== */
static int test_full_buffer_drop(void)
{
    UartRing ring;
    uart_ring_init(&ring);

    /* Fill completely */
    unsigned i;
    for (i = 0U; i < UART_RING_SIZE; i++) {
        CHECK(uart_ring_push(&ring, (uint8_t)i));
    }

    /* Ring is now full.  Next push must fail. */
    CHECK(uart_ring_push(&ring, 0xFF) == 0U);

    /* overflow_drops must be 1 */
    CHECK(ring.overflow_drops == 1U);

    /* Pop one slot, then push again should succeed */
    uint8_t b;
    CHECK(uart_ring_pop(&ring, &b));
    CHECK(uart_ring_push(&ring, 0xFE));

    /* overflow_drops unchanged */
    CHECK(ring.overflow_drops == 1U);

    /* Drain and verify 0xFF was never written — the dropped byte is lost */
    uint8_t buf[UART_RING_SIZE];
    uint16_t n = uart_ring_drain(&ring, buf, sizeof(buf));
    CHECK(n == UART_RING_SIZE);   /* full ring re-read: dropped one, added one */
    CHECK(buf[UART_RING_SIZE - 1U] == 0xFE);
    return 0;
}

/* ======================================================================
 * Test: drain from empty ring returns zero.
 * ====================================================================== */
static int test_empty_drain_returns_zero(void)
{
    UartRing ring;
    uart_ring_init(&ring);
    uint8_t buf[16];
    CHECK(uart_ring_drain(&ring, buf, sizeof(buf)) == 0U);
    return 0;
}

/* ======================================================================
 * Test: drain returns correct number of bytes.
 * ====================================================================== */
static int test_drain_count_matches(void)
{
    UartRing ring;
    uart_ring_init(&ring);

    CHECK(uart_ring_push(&ring, 0x01));
    CHECK(uart_ring_push(&ring, 0x02));
    CHECK(uart_ring_push(&ring, 0x03));

    uint8_t buf[4];
    CHECK(uart_ring_drain(&ring, buf, sizeof(buf)) == 3U);
    CHECK(buf[0] == 0x01);
    CHECK(buf[1] == 0x02);
    CHECK(buf[2] == 0x03);
    return 0;
}

/* ======================================================================
 * Test: drain with undersized buffer returns min(count, capacity).
 * ====================================================================== */
static int test_drain_truncated(void)
{
    UartRing ring;
    uart_ring_init(&ring);

    CHECK(uart_ring_push(&ring, 0x10));
    CHECK(uart_ring_push(&ring, 0x20));
    CHECK(uart_ring_push(&ring, 0x30));

    uint8_t buf[2];
    CHECK(uart_ring_drain(&ring, buf, sizeof(buf)) == 2U);
    CHECK(buf[0] == 0x10);
    CHECK(buf[1] == 0x20);

    /* Remaining byte should still be in the ring */
    uint8_t b;
    CHECK(uart_ring_pop(&ring, &b));
    CHECK(b == 0x30);
    return 0;
}

/* ======================================================================
 * Test: counters initialise to zero then reflect pushes.
 * ====================================================================== */
static int test_counters_after_push(void)
{
    UartRing ring;
    uart_ring_init(&ring);

    CHECK(ring.rx_bytes == 0U);
    CHECK(ring.overflow_drops == 0U);
    CHECK(ring.ore_events == 0U);

    uart_ring_push(&ring, 0xA0);
    uart_ring_push(&ring, 0xB0);

    CHECK(ring.rx_bytes == 2U);
    CHECK(ring.overflow_drops == 0U);
    return 0;
}

/* ======================================================================
 * Test: push/pop from alternate halves does not corrupt data.
 * ====================================================================== */
static int test_alternating_push_pop(void)
{
    UartRing ring;
    uart_ring_init(&ring);

    /* Push one, pop one, many times */
    unsigned i;
    for (i = 0U; i < 100U; i++) {
        CHECK(uart_ring_push(&ring, (uint8_t)(i & 0xFF)));
        uint8_t b;
        CHECK(uart_ring_pop(&ring, &b));
        CHECK(b == (uint8_t)(i & 0xFF));
    }
    CHECK(ring.rx_bytes == 100U);
    CHECK(ring.overflow_drops == 0U);
    return 0;
}

/* ======================================================================
 * Test: push exactly UART_RING_SIZE bytes, then drain all.
 * ====================================================================== */
static int test_full_cycle(void)
{
    UartRing ring;
    uart_ring_init(&ring);

    unsigned i;
    for (i = 0U; i < UART_RING_SIZE; i++) {
        CHECK(uart_ring_push(&ring, (uint8_t)i));
    }

    uint8_t buf[UART_RING_SIZE];
    uint16_t n = uart_ring_drain(&ring, buf, sizeof(buf));
    CHECK(n == UART_RING_SIZE);

    for (i = 0U; i < UART_RING_SIZE; i++) {
        CHECK(buf[i] == (uint8_t)i);
    }
    CHECK(ring.overflow_drops == 0U);
    return 0;
}

/* ======================================================================
 * Test: high_water mark for RX and TX ring instances (health baseline Task 4)
 * ====================================================================== */
static int high_water_sequence(UartRing *ring)
{
    uint8_t b;
    unsigned i;
    CHECK(ring->high_water == 0U);   /* init clears */

    /* Fresh push peak. */
    for (i = 0U; i < 50U; i++) CHECK(uart_ring_push(ring, (uint8_t)i));
    CHECK(ring->high_water == 50U);

    /* Pop never lowers the peak. */
    for (i = 0U; i < 30U; i++) CHECK(uart_ring_pop(ring, &b));
    CHECK(ring->high_water == 50U);

    /* Push past the previous peak -> new peak. */
    for (i = 0U; i < 40U; i++) CHECK(uart_ring_push(ring, (uint8_t)(0x80U | i)));
    CHECK(ring->high_water == 60U);

    /* Fill to full -> high_water == 128. */
    for (i = 0U; i < UART_RING_SIZE - 60U; i++) CHECK(uart_ring_push(ring, (uint8_t)i));
    CHECK(ring->high_water == UART_RING_SIZE);

    /* Overflow push does not raise the peak beyond the full mark. */
    CHECK(uart_ring_push(ring, 0xEE) == 0U);
    CHECK(ring->high_water == UART_RING_SIZE);

    /* Drain keeps the peak (only rises, never falls). */
    while (uart_ring_pop(ring, &b));
    CHECK(ring->high_water == UART_RING_SIZE);
    return 0;
}

static int test_high_water_rx_and_tx(void)
{
    UartRing rx;   /* RX instance */
    UartRing tx;   /* TX instance (same UartRing struct, design §4.5) */
    uart_ring_init(&rx);
    uart_ring_init(&tx);
    if (high_water_sequence(&rx)) return 1;
    if (high_water_sequence(&tx)) return 1;
    return 0;
}

/* ======================================================================
 * Main
 * ====================================================================== */
int main(void)
{
    unsigned failures = 0U;

#define RUN(fn) do { \
    if (fn()) { \
        fprintf(stderr, "FAIL: %s\n", #fn); \
        failures++; \
    } \
} while (0)

    RUN(test_push_pop_fifo_order);
    RUN(test_wraparound);
    RUN(test_full_buffer_drop);
    RUN(test_empty_drain_returns_zero);
    RUN(test_drain_count_matches);
    RUN(test_drain_truncated);
    RUN(test_counters_after_push);
    RUN(test_alternating_push_pop);
    RUN(test_full_cycle);
    RUN(test_high_water_rx_and_tx);

    if (failures == 0U) {
        puts("PASS test_uart_ring");
        return 0;
    }
    fprintf(stderr, "FAILED %u test(s)\n", failures);
    return 1;
}
