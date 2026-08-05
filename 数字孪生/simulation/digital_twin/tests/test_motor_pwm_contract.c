#include <stdio.h>
#include <string.h>

#include "stm32f10x.h"
#include "Motor.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

TIM_TypeDef g_test_tim2 = {2U, {0U, 0U, 0U, 0U}, 0};
TIM_TypeDef g_test_tim4 = {4U, {0U, 0U, 0U, 0U}, 0};
GPIO_TypeDef g_test_gpioa = {1U};
GPIO_TypeDef g_test_gpiob = {2U};

static TIM_TimeBaseInitTypeDef g_tim2_base;
static TIM_TimeBaseInitTypeDef g_tim4_base;
static int g_tim2_base_seen;
static int g_tim4_base_seen;

void RCC_APB1PeriphClockCmd(uint32_t p, FunctionalState s) {(void)p; (void)s;}
void RCC_APB2PeriphClockCmd(uint32_t p, FunctionalState s) {(void)p; (void)s;}
void GPIO_Init(GPIO_TypeDef *g, GPIO_InitTypeDef *c) {(void)g; (void)c;}
void TIM_InternalClockConfig(TIM_TypeDef *t) {(void)t;}
void TIM_TimeBaseInit(TIM_TypeDef *t, TIM_TimeBaseInitTypeDef *c)
{
    if (t == TIM2) { g_tim2_base = *c; g_tim2_base_seen = 1; }
    if (t == TIM4) { g_tim4_base = *c; g_tim4_base_seen = 1; }
}
void TIM_OCStructInit(TIM_OCInitTypeDef *c) { memset(c, 0, sizeof(*c)); }
void TIM_OC1Init(TIM_TypeDef *t, TIM_OCInitTypeDef *c) {(void)t; (void)c;}
void TIM_OC2Init(TIM_TypeDef *t, TIM_OCInitTypeDef *c) {(void)t; (void)c;}
void TIM_OC3Init(TIM_TypeDef *t, TIM_OCInitTypeDef *c) {(void)t; (void)c;}
void TIM_OC4Init(TIM_TypeDef *t, TIM_OCInitTypeDef *c) {(void)t; (void)c;}
void TIM_Cmd(TIM_TypeDef *t, FunctionalState s) { t->enabled = (s == ENABLE); }
void TIM_SetCompare1(TIM_TypeDef *t, uint16_t v) { t->ccr[0] = v; }
void TIM_SetCompare2(TIM_TypeDef *t, uint16_t v) { t->ccr[1] = v; }
void TIM_SetCompare3(TIM_TypeDef *t, uint16_t v) { t->ccr[2] = v; }
void TIM_SetCompare4(TIM_TypeDef *t, uint16_t v) { t->ccr[3] = v; }

static void clear_ccr(void)
{
    memset(g_test_tim2.ccr, 0, sizeof(g_test_tim2.ccr));
    memset(g_test_tim4.ccr, 0, sizeof(g_test_tim4.ccr));
}

static int test_timer_contract(void)
{
    Motor_Init();
    CHECK(g_tim2_base_seen == 1);
    CHECK(g_tim4_base_seen == 1);
    CHECK(g_tim2_base.TIM_Prescaler == 71U);
    CHECK(g_tim4_base.TIM_Prescaler == 71U);
    CHECK(g_tim2_base.TIM_Period == 999U);
    CHECK(g_tim4_base.TIM_Period == 999U);
    CHECK(g_test_tim2.enabled == 1);
    CHECK(g_test_tim4.enabled == 1);
    return 0;
}

static int test_signed_channels_and_clamp(void)
{
    clear_ccr();
    Motor_Write(260, 260, 260, 260);
    CHECK(g_test_tim2.ccr[0] == 0U && g_test_tim2.ccr[1] == 260U);
    CHECK(g_test_tim2.ccr[2] == 260U && g_test_tim2.ccr[3] == 0U);
    CHECK(g_test_tim4.ccr[0] == 260U && g_test_tim4.ccr[1] == 0U);
    CHECK(g_test_tim4.ccr[2] == 0U && g_test_tim4.ccr[3] == 260U);

    clear_ccr();
    Motor_Write(1200, -1200, 999, -999);
    CHECK(g_test_tim2.ccr[0] == 0U && g_test_tim2.ccr[1] == 999U);
    CHECK(g_test_tim2.ccr[2] == 0U && g_test_tim2.ccr[3] == 999U);
    CHECK(g_test_tim4.ccr[0] == 999U && g_test_tim4.ccr[1] == 0U);
    CHECK(g_test_tim4.ccr[2] == 999U && g_test_tim4.ccr[3] == 0U);
    return 0;
}

int main(void)
{
    if (test_timer_contract()) return 1;
    if (test_signed_channels_and_clamp()) return 1;
    puts("PASS test_motor_pwm_contract");
    return 0;
}
