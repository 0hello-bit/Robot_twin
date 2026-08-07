#ifndef UART_RING_H
#define UART_RING_H

#include <stdint.h>

/* Fixed capacity - must be power of 2.  The TX instance must hold one
   complete 248-byte droppable telemetry batch after the CIPSEND prompt. */
#define UART_RING_SIZE 256U
#define UART_RING_MASK (UART_RING_SIZE - 1U)

/* Single-producer single-consumer lock-free ring buffer.
   ISR (producer) calls uart_ring_push; main context (consumer) calls
   uart_ring_pop / uart_ring_drain.  No mutual exclusion needed because
   only one reader and one writer, and each only touches its own index. */
typedef struct {
    volatile uint8_t buf[UART_RING_SIZE];
    volatile uint16_t head;          /* producer write index       */
    volatile uint16_t tail;          /* consumer read index        */
    volatile uint32_t rx_bytes;      /* total bytes received       */
    volatile uint32_t overflow_drops;/* bytes dropped when full    */
    volatile uint32_t ore_events;    /* ORE flag observed count    */
    volatile uint16_t high_water;    /* historical peak occupancy  */
} UartRing;

/* Initialise ring and counters to zero.  Call once before enabling
   the USART RXNE interrupt. */
void uart_ring_init(UartRing *ring);

/* ISR-safe producer: store one byte.
   Returns 1 on success, 0 if ring is full (byte dropped). */
uint8_t uart_ring_push(UartRing *ring, uint8_t byte);

/* Main-context consumer: retrieve one byte (non-blocking).
   Returns 1 if *byte is valid, 0 if ring empty. */
uint8_t uart_ring_pop(UartRing *ring, uint8_t *byte);

/* Drain all currently available bytes into a linear buffer.
   Returns the number of bytes written to buf (0 if empty). */
uint16_t uart_ring_drain(UartRing *ring, uint8_t *buf, uint16_t capacity);

#endif /* UART_RING_H */
