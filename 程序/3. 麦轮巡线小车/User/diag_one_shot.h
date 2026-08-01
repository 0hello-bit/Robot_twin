#ifndef DIAG_ONE_SHOT_H
#define DIAG_ONE_SHOT_H

/*============================================================================
 * diag_one_shot.h — One-shot diagnostic arm state machine
 *
 * Pure logic — no hardware dependencies, compiles with ARMCC5 and MSVC.
 *
 * Tracks the inhibited→running transition so the motor-register diagnostic
 * frame (type 0x7E) is emitted exactly once per START epoch.
 *
 * State transition table:
 *   ┌─────────────────────┬──────────────────────┬──────────────────────┐
 *   │ Event               │ armed (output)       │ was_inhibited (next) │
 *   ├─────────────────────┼──────────────────────┼──────────────────────┤
 *   │ init()              │ 0                    │ 1                    │
 *   │ update(inhibited)   │ 0, was_inhibited ← 1 │ 1                    │
 *   │ update(!inhibited)  │ if was_inhibited     │ 0                    │
 *   │   first time        │   then armed ← 1     │                      │
 *   │   later times       │   armed unchanged    │                      │
 *   │ consume()           │ clears armed, returns│ unchanged            │
 *   │                     │   previous value     │                      │
 *   └─────────────────────┴──────────────────────┴──────────────────────┘
 *============================================================================*/

#include <stdint.h>

typedef struct {
    uint8_t armed;          /* 1 = send frame on next Diag_CaptureAndSendOnce */
    uint8_t was_inhibited;  /* 1 = previous loop iteration was inhibited */
} DiagOneShot;

/* Initialise state.  Boot starts with motion inhibited per
   twin_control_init(), so was_inhibited = 1. */
static inline void diag_one_shot_init(DiagOneShot *s)
{
    s->armed = 0;
    s->was_inhibited = 1;
}

/* Update state for one loop iteration.
   Call once per loop, before the MotorOut / capture decision.
   motion_inhibited = 1 when the controller is in the inhibited branch,
   0 when motion is permitted (running epoch). */
static inline void diag_one_shot_update(DiagOneShot *s, uint8_t motion_inhibited)
{
    if (motion_inhibited) {
        /* Motion inhibited — reset the armed flag and remember
           this state so a future transition to running re-arms. */
        s->armed = 0;
        s->was_inhibited = 1;
    } else {
        /* Running epoch — arm exactly once on the first iteration
           after an inhibited epoch. */
        if (s->was_inhibited) {
            s->armed = 1;
            s->was_inhibited = 0;
        }
    }
}

/* Peek at the armed flag without consuming it.
   Returns 1 if a frame is pending. */
static inline uint8_t diag_one_shot_peek(const DiagOneShot *s)
{
    return s->armed;
}

/* Consume the armed flag.
   Returns 1 if a diagnostic frame should be sent this iteration,
   then clears the flag.  Safe to call even when not armed. */
static inline uint8_t diag_one_shot_consume(DiagOneShot *s)
{
    uint8_t a = s->armed;
    s->armed = 0;
    return a;
}

#endif /* DIAG_ONE_SHOT_H */
