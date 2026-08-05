/******************************************************************************
 * uart_ring.c — Fixed-capacity SPSC lock-free ring buffer for UART RX.
 *
 * Single producer (USART1_IRQHandler) / single consumer (main loop).
 * ARMCC5 / C90-compatible.  No dynamic allocation.
 *
 * Usage:
 *   1. Call uart_ring_init() before enabling the RXNE interrupt.
 *   2. In the ISR: call uart_ring_push() — fast, no parsing.
 *   3. In main: call uart_ring_pop() or uart_ring_drain().
 *   4. Read observable counters: ring->rx_bytes, overflow_drops, ore_events.
 ******************************************************************************/
#include "uart_ring.h"

void uart_ring_init(UartRing *ring)
{
    ring->head = 0U;
    ring->tail = 0U;
    ring->rx_bytes = 0U;
    ring->overflow_drops = 0U;
    ring->ore_events = 0U;
    ring->high_water = 0U;
}

uint8_t uart_ring_push(UartRing *ring, uint8_t byte)
{
    uint16_t h = ring->head;
    uint16_t t = ring->tail;
    uint16_t used = (uint16_t)(h - t);

    if (used >= UART_RING_SIZE) {
        /* Ring full — drop byte */
        ring->overflow_drops++;
        return 0U;
    }

    ring->buf[h & UART_RING_MASK] = byte;
    ring->head = (uint16_t)(h + 1U);
    ring->rx_bytes++;
    /* Health baseline (Task 4): historical peak occupancy (ISR side, 2
       compares). RX/TX two rings both use the same push, so both record. */
    if ((uint16_t)(used + 1U) > ring->high_water) {
        ring->high_water = (uint16_t)(used + 1U);
    }
    return 1U;
}

uint8_t uart_ring_pop(UartRing *ring, uint8_t *byte)
{
    uint16_t h = ring->head;
    uint16_t t = ring->tail;

    if (h == t) {
        return 0U;  /* empty */
    }

    *byte = ring->buf[t & UART_RING_MASK];
    ring->tail = (uint16_t)(t + 1U);
    return 1U;
}

uint16_t uart_ring_drain(UartRing *ring, uint8_t *buf, uint16_t capacity)
{
    uint16_t count = 0U;

    while (count < capacity) {
        uint16_t h = ring->head;
        uint16_t t = ring->tail;
        if (h == t) break;

        buf[count] = ring->buf[t & UART_RING_MASK];
        ring->tail = (uint16_t)(t + 1U);
        count++;
    }

    return count;
}
