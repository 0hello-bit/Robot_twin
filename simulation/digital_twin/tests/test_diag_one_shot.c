/*============================================================================
 * test_diag_one_shot.c — Host C tests for diagnostic one-shot state machine
 *
 * Tests the DiagOneShot transition logic that ensures exactly one
 * type-0x7E diagnostic frame is emitted per inhibited→running transition.
 *
 * These are pure logic tests — no hardware dependencies.
 *============================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "diag_one_shot.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

/* Boot starts inhibited — frame should NOT be armed yet. */
static int test_boot_inhibited_not_armed(void)
{
    DiagOneShot s;
    diag_one_shot_init(&s);

    CHECK(s.was_inhibited == 1);
    CHECK(s.armed == 0);
    CHECK(diag_one_shot_consume(&s) == 0);  /* consume while not armed */
    return 0;
}

/* First transition inhibited → running: arms once. */
static int test_first_start_arms_once(void)
{
    DiagOneShot s;
    diag_one_shot_init(&s);

    /* Enter running epoch */
    diag_one_shot_update(&s, 0);  /* motion NOT inhibited */
    CHECK(s.armed == 1);
    CHECK(s.was_inhibited == 0);

    /* Consume the arm */
    CHECK(diag_one_shot_consume(&s) == 1);
    CHECK(s.armed == 0);          /* cleared after consume */

    /* Consuming again should return 0 */
    CHECK(diag_one_shot_consume(&s) == 0);
    return 0;
}

/* Repeated running loops do NOT rearm. */
static int test_repeated_running_does_not_rearm(void)
{
    DiagOneShot s;
    diag_one_shot_init(&s);

    /* First running iteration arms */
    diag_one_shot_update(&s, 0);
    CHECK(s.armed == 1);
    diag_one_shot_consume(&s);

    /* Second running iteration — should NOT rearm */
    diag_one_shot_update(&s, 0);
    CHECK(s.armed == 0);
    CHECK(diag_one_shot_consume(&s) == 0);

    /* Third running iteration — still not rearmed */
    diag_one_shot_update(&s, 0);
    CHECK(s.armed == 0);
    return 0;
}

/* STOP (inhibited) resets state — re-arms on next START. */
static int test_stop_resets_and_next_start_rearms(void)
{
    DiagOneShot s;
    diag_one_shot_init(&s);

    /* First start → running, arm, consume */
    diag_one_shot_update(&s, 0);
    CHECK(diag_one_shot_consume(&s) == 1);

    /* Several running iterations (no rearm) */
    diag_one_shot_update(&s, 0);
    CHECK(diag_one_shot_consume(&s) == 0);
    diag_one_shot_update(&s, 0);
    CHECK(diag_one_shot_consume(&s) == 0);

    /* STOP — motion inhibited */
    diag_one_shot_update(&s, 1);  /* inhibited */
    CHECK(s.armed == 0);
    CHECK(s.was_inhibited == 1);  /* remembers inhibited state */
    CHECK(diag_one_shot_consume(&s) == 0);

    /* Second start — should arm again */
    diag_one_shot_update(&s, 0);
    CHECK(s.armed == 1);
    CHECK(diag_one_shot_consume(&s) == 1);

    /* Subsequent running — no rearm */
    diag_one_shot_update(&s, 0);
    CHECK(diag_one_shot_consume(&s) == 0);
    return 0;
}

/* Repeated STOP remains safe — never arms while inhibited. */
static int test_repeated_stop_safe(void)
{
    DiagOneShot s;
    diag_one_shot_init(&s);

    /* Multiple inhibited iterations */
    diag_one_shot_update(&s, 1);
    CHECK(s.armed == 0);
    CHECK(diag_one_shot_consume(&s) == 0);

    diag_one_shot_update(&s, 1);
    CHECK(s.armed == 0);

    diag_one_shot_update(&s, 1);
    CHECK(s.armed == 0);
    CHECK(s.was_inhibited == 1);
    return 0;
}

/* Full lifecycle: boot → run → stop → run → stop → stop → run */
static int test_full_lifecycle(void)
{
    DiagOneShot s;
    diag_one_shot_init(&s);

    /* Phase 1: Boot (inhibited) */
    CHECK(diag_one_shot_consume(&s) == 0);

    /* Phase 2: First start → running */
    diag_one_shot_update(&s, 0);
    CHECK(s.armed == 1);
    CHECK(diag_one_shot_consume(&s) == 1);

    /* Phase 3: Running repeats */
    diag_one_shot_update(&s, 0);
    CHECK(diag_one_shot_consume(&s) == 0);
    diag_one_shot_update(&s, 0);
    CHECK(diag_one_shot_consume(&s) == 0);

    /* Phase 4: STOP */
    diag_one_shot_update(&s, 1);
    CHECK(s.armed == 0);
    CHECK(s.was_inhibited == 1);

    /* Phase 5: Second start */
    diag_one_shot_update(&s, 0);
    CHECK(s.armed == 1);
    CHECK(diag_one_shot_consume(&s) == 1);

    /* Phase 6: Running */
    diag_one_shot_update(&s, 0);
    CHECK(diag_one_shot_consume(&s) == 0);

    /* Phase 7: Another STOP */
    diag_one_shot_update(&s, 1);
    CHECK(s.armed == 0);

    /* Phase 8: Still stopped */
    diag_one_shot_update(&s, 1);
    CHECK(s.armed == 0);

    /* Phase 9: Third start */
    diag_one_shot_update(&s, 0);
    CHECK(s.armed == 1);
    CHECK(diag_one_shot_consume(&s) == 1);

    /* Phase 10: Running no rearm */
    diag_one_shot_update(&s, 0);
    CHECK(diag_one_shot_consume(&s) == 0);
    return 0;
}

/* update() on already-inhibited state preserves was_inhibited */
static int test_inhibited_idempotent(void)
{
    DiagOneShot s;
    diag_one_shot_init(&s);

    diag_one_shot_update(&s, 1);
    CHECK(s.was_inhibited == 1);
    CHECK(s.armed == 0);

    diag_one_shot_update(&s, 1);
    CHECK(s.was_inhibited == 1);
    CHECK(s.armed == 0);
    return 0;
}

/* consume() on a newly-init state returns 0 */
static int test_consume_after_init(void)
{
    DiagOneShot s;
    diag_one_shot_init(&s);
    CHECK(diag_one_shot_consume(&s) == 0);
    CHECK(diag_one_shot_consume(&s) == 0);  /* idempotent zero */
    return 0;
}

/* peek() sees armed state without consuming */
static int test_peek_before_consume(void)
{
    DiagOneShot s;
    diag_one_shot_init(&s);

    /* Not armed — peek returns 0 */
    CHECK(diag_one_shot_peek(&s) == 0);

    /* Arm it */
    diag_one_shot_update(&s, 0);
    CHECK(diag_one_shot_peek(&s) == 1);

    /* Peek is non-destructive */
    CHECK(diag_one_shot_peek(&s) == 1);
    CHECK(diag_one_shot_peek(&s) == 1);

    /* Consume clears it */
    CHECK(diag_one_shot_consume(&s) == 1);
    CHECK(diag_one_shot_peek(&s) == 0);
    return 0;
}

int main(void)
{
    int failed = 0;

    failed += test_boot_inhibited_not_armed();
    failed += test_first_start_arms_once();
    failed += test_repeated_running_does_not_rearm();
    failed += test_stop_resets_and_next_start_rearms();
    failed += test_repeated_stop_safe();
    failed += test_full_lifecycle();
    failed += test_inhibited_idempotent();
    failed += test_consume_after_init();
    failed += test_peek_before_consume();

    if (failed) {
        fprintf(stderr, "%d test(s) FAILED\n", failed);
        return 1;
    }
    printf("All diag_one_shot tests PASSED.\n");
    return 0;
}
