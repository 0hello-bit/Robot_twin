/* Host C test for the IWDG thin-layer constants (firmware health baseline,
 * Task 6).  The watchdog itself is hardware-bound (stm32f10x_iwdg), so only
 * the parameter constants are host-testable: PR division 64, RLR=1249, and
 * the recomputable LSI range table (design §7.2: 1333 / 2000 / 2667 ms).
 *
 * TDD: RED = header absent -> cl cannot open source file; GREEN = constants
 * match the authoritative values.  Constants are read through volatile locals
 * so the runtime comparisons are not compile-time constants (avoids C4127
 * under /W4 /WX).
 */

#include <stdio.h>

#include "health_watchdog.h"

#define CHECK(expression) do { \
    if (!(expression)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expression); \
        return 1; \
    } \
} while (0)

static int test_watchdog_constants(void)
{
    volatile unsigned prescaler_div = HEALTH_IWDG_PRESCALER_DIV;
    volatile unsigned reload_value  = HEALTH_IWDG_RELOAD_VALUE;
    volatile unsigned nominal_ms    = HEALTH_IWDG_NOMINAL_MS;
    volatile unsigned min_ms        = HEALTH_IWDG_MIN_MS;
    volatile unsigned max_ms        = HEALTH_IWDG_MAX_MS;

    CHECK(prescaler_div == 64U);
    CHECK(reload_value == 1249U);
    CHECK(nominal_ms == 2000U);
    CHECK(min_ms == 1333U);
    CHECK(max_ms == 2667U);

    /* Recomputable: t = PR × (RLR+1) / f_LSI, PR=64, RLR=1249, RLR+1=1250.
         40kHz -> 64×1250/40000 = 2000 ms (nominal)
         60kHz -> 64×1250/60000 ≈ 1333.3 ms (lower bound)
         30kHz -> 64×1250/30000 ≈ 2666.7 ms (upper bound) */
    return 0;
}

int main(void)
{
    if (test_watchdog_constants()) return 1;
    puts("PASS test_health_watchdog");
    return 0;
}
