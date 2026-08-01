/* Host C tests for the monotonic time core (Task 4B-4 fix group B).
 *
 * Covers the pure time logic used by the firmware:
 *   - mono_elapsed_ms: 回绕安全的差值（正常 / 跨越 2^32 回绕）。
 *   - mono_clamp_dt_ms: 边界保护（零 dt → 钳到 min；异常大间隔 → 钳到 max）。
 *   - mono_is_after_ms: 截止判断（前后 / 相等 / 回绕）。
 *   - yaw dt 组合逻辑：零 dt、正常 dt、异常大间隔分别得到受保护 dt。
 */

#include <stdio.h>
#include <stdint.h>
#include "mono_time_core.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static int test_elapsed_normal(void)
{
    CHECK(mono_elapsed_ms(1000U, 1005U) == 5U);
    CHECK(mono_elapsed_ms(0U, 100U) == 100U);
    CHECK(mono_elapsed_ms(100U, 100U) == 0U);
    return 0;
}

static int test_elapsed_wraparound(void)
{
    /* 跨越 2^32 回绕：prev 接近 2^32-1，now 从 0 重新开始 */
    CHECK(mono_elapsed_ms(0xFFFFFFF0U, 0x0000000AU) == 0x1AU);
    CHECK(mono_elapsed_ms(0xFFFFFFF0U, 0x00000010U) == 0x20U);
    return 0;
}

static int test_elapsed_large_span_no_wrap(void)
{
    /* 大跨度（< 2^31 ms）不回绕时正确 */
    CHECK(mono_elapsed_ms(1000U, 4000000000U) == 3999999000U);
    return 0;
}

static int test_clamp_dt_bounds(void)
{
    /* 零 dt → 钳到 min */
    CHECK(mono_clamp_dt_ms(0U, 1U, 100U) == 1U);
    /* 正常 dt → 不变 */
    CHECK(mono_clamp_dt_ms(5U, 1U, 100U) == 5U);
    /* 异常大间隔 → 钳到 max */
    CHECK(mono_clamp_dt_ms(1000000U, 1U, 100U) == 100U);
    CHECK(mono_clamp_dt_ms(100U, 1U, 100U) == 100U);
    CHECK(mono_clamp_dt_ms(1U, 1U, 100U) == 1U);
    return 0;
}

static int test_is_after_ms(void)
{
    CHECK(mono_is_after_ms(101U, 100U) == 1U);   /* now 在 base 之后 */
    CHECK(mono_is_after_ms(100U, 100U) == 1U);   /* 相等 */
    CHECK(mono_is_after_ms(99U, 100U) == 0U);    /* now 在 base 之前 */
    /* 回绕：now 小数值但在 base 之后（跨越回绕点） */
    CHECK(mono_is_after_ms(5U, 0xFFFFFFF0U) == 1U);
    return 0;
}

static int test_yaw_dt_combination(void)
{
    /* 零 dt：两次采样同一毫秒 → dt 钳到 min（1ms），不会除以零/零积分 */
    uint32_t dt0 = mono_clamp_dt_ms(mono_elapsed_ms(1000U, 1000U), 1U, 100U);
    CHECK(dt0 == 1U);

    /* 正常 dt：5ms 采样间隔 */
    uint32_t dt1 = mono_clamp_dt_ms(mono_elapsed_ms(1000U, 1005U), 1U, 100U);
    CHECK(dt1 == 5U);

    /* 异常大间隔：卡顿 1s → 钳到 max（100ms），避免 yaw 积分跳变 */
    uint32_t dt2 = mono_clamp_dt_ms(mono_elapsed_ms(1000U, 1001000U), 1U, 100U);
    CHECK(dt2 == 100U);
    return 0;
}

static int run_all_tests(void)
{
    if (test_elapsed_normal()) return 1;
    if (test_elapsed_wraparound()) return 1;
    if (test_elapsed_large_span_no_wrap()) return 1;
    if (test_clamp_dt_bounds()) return 1;
    if (test_is_after_ms()) return 1;
    if (test_yaw_dt_combination()) return 1;
    puts("PASS test_mono_time_core");
    return 0;
}

int main(void)
{
    return run_all_tests();
}
