# PWM Permille Scale Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make motor commands `0..999` produce approximately `0..99.9%` duty on TIM2 and TIM4 while preserving every direction, control, and safety behavior.

**Architecture:** Compile the real production `Motor.c` against a test-only STM32 peripheral stub, then assert observable timer and CCR effects. After recording the current `ARR=4234` RED failure, bind the clamp and timer period to one private compile-time constant and verify the locked Keil target.

**Tech Stack:** STM32F10x Standard Peripheral Library API, C, MSVC host tests, Python 3.11 pytest, Keil MDK/uVision.

## Global Constraints

- Do not change `M1_DIR..M4_DIR`, PWM channel selection, or `MotorOut()` grouping.
- Do not change PID gains, speed bounds, smoothing, lost-line behavior, runtime protocol, heartbeat, STOP, or rollback.
- Do not connect to the ESP, camera, serial port, debugger, or real car.
- Do not flash firmware or issue motion commands.
- Do not perform Git writes; preserve all unrelated dirty-worktree changes.
- Store generated executables and logs only under a new `.embeddedskills/build/v1_pwm_permille_repair_20260805_r1/` directory.

---

## File Structure

- Create `simulation/digital_twin/tests/motor_stubs/stm32f10x.h`: test-only subset of the STM32 API used by `Motor.c`.
- Create `simulation/digital_twin/tests/test_motor_pwm_contract.c`: host test that links the real `Motor.c` and observes timer/CCR effects.
- Modify `程序/3. 麦轮巡线小车/Hardware/Motor.c`: private shared PWM constants and consistent TIM2/TIM4 period.
- Generate `.embeddedskills/build/v1_pwm_permille_repair_20260805_r1/`: pre-edit source snapshot, RED/GREEN executables, and Keil logs; no historical evidence is overwritten.

### Task 1: Real Motor PWM Contract, RED Then GREEN

**Files:**
- Create: `simulation/digital_twin/tests/motor_stubs/stm32f10x.h`
- Create: `simulation/digital_twin/tests/test_motor_pwm_contract.c`
- Modify: `程序/3. 麦轮巡线小车/Hardware/Motor.c:4-12,57-79`

**Interfaces:**
- Consumes: production `Motor_Init(void)` and `Motor_Write(int16_t,int16_t,int16_t,int16_t)` from `Motor.h`/`Motor.c`.
- Produces: a host executable that exits 0 only when both timers use ARR 999 and signed commands/clamping reach the expected CCR channels.

- [ ] **Step 1: Add the test-only STM32 API stub**

Create `simulation/digital_twin/tests/motor_stubs/stm32f10x.h` with this content:

```c
#ifndef TEST_STM32F10X_H
#define TEST_STM32F10X_H

#include <stdint.h>

typedef enum { DISABLE = 0, ENABLE = 1 } FunctionalState;

typedef struct {
    uint16_t GPIO_Pin;
    uint32_t GPIO_Speed;
    uint32_t GPIO_Mode;
} GPIO_InitTypeDef;

typedef struct {
    uint16_t TIM_Prescaler;
    uint16_t TIM_CounterMode;
    uint16_t TIM_Period;
    uint16_t TIM_ClockDivision;
    uint8_t TIM_RepetitionCounter;
} TIM_TimeBaseInitTypeDef;

typedef struct {
    uint16_t TIM_OCMode;
    uint16_t TIM_OutputState;
    uint16_t TIM_Pulse;
    uint16_t TIM_OCPolarity;
} TIM_OCInitTypeDef;

typedef struct {
    unsigned id;
    uint16_t ccr[4];
    int enabled;
} TIM_TypeDef;

typedef struct { unsigned id; } GPIO_TypeDef;

extern TIM_TypeDef g_test_tim2;
extern TIM_TypeDef g_test_tim4;
extern GPIO_TypeDef g_test_gpioa;
extern GPIO_TypeDef g_test_gpiob;

#define TIM2 (&g_test_tim2)
#define TIM4 (&g_test_tim4)
#define GPIOA (&g_test_gpioa)
#define GPIOB (&g_test_gpiob)

#define RCC_APB1Periph_TIM2 1U
#define RCC_APB1Periph_TIM4 2U
#define RCC_APB2Periph_GPIOA 4U
#define RCC_APB2Periph_GPIOB 8U
#define GPIO_Pin_0  (1U << 0)
#define GPIO_Pin_1  (1U << 1)
#define GPIO_Pin_2  (1U << 2)
#define GPIO_Pin_3  (1U << 3)
#define GPIO_Pin_6  (1U << 6)
#define GPIO_Pin_7  (1U << 7)
#define GPIO_Pin_8  (1U << 8)
#define GPIO_Pin_9  (1U << 9)
#define GPIO_Mode_AF_PP 2U
#define GPIO_Speed_50MHz 50U
#define TIM_CKD_DIV1 0U
#define TIM_CounterMode_Up 0U
#define TIM_OCMode_PWM1 1U
#define TIM_OCPolarity_High 1U
#define TIM_OutputState_Enable 1U

void RCC_APB1PeriphClockCmd(uint32_t peripheral, FunctionalState state);
void RCC_APB2PeriphClockCmd(uint32_t peripheral, FunctionalState state);
void GPIO_Init(GPIO_TypeDef *gpio, GPIO_InitTypeDef *config);
void TIM_InternalClockConfig(TIM_TypeDef *timer);
void TIM_TimeBaseInit(TIM_TypeDef *timer, TIM_TimeBaseInitTypeDef *config);
void TIM_OCStructInit(TIM_OCInitTypeDef *config);
void TIM_OC1Init(TIM_TypeDef *timer, TIM_OCInitTypeDef *config);
void TIM_OC2Init(TIM_TypeDef *timer, TIM_OCInitTypeDef *config);
void TIM_OC3Init(TIM_TypeDef *timer, TIM_OCInitTypeDef *config);
void TIM_OC4Init(TIM_TypeDef *timer, TIM_OCInitTypeDef *config);
void TIM_Cmd(TIM_TypeDef *timer, FunctionalState state);
void TIM_SetCompare1(TIM_TypeDef *timer, uint16_t value);
void TIM_SetCompare2(TIM_TypeDef *timer, uint16_t value);
void TIM_SetCompare3(TIM_TypeDef *timer, uint16_t value);
void TIM_SetCompare4(TIM_TypeDef *timer, uint16_t value);

#endif
```

- [ ] **Step 2: Add the real-behavior host test**

Create `simulation/digital_twin/tests/test_motor_pwm_contract.c`. The complete test must:

```c
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
```

- [ ] **Step 3: Snapshot production source, then build and run RED**

Create the new output directory with `exist_ok=false` semantics. Copy the
untouched production `Motor.c` to `Motor.c.before` and record both SHA-256
hashes before editing. Then run this from the workspace root, first with
`$phase='red'` and later with `$phase='green'`:

```powershell
$root = (Resolve-Path '.').Path
$evidence = Join-Path $root '.embeddedskills\build\v1_pwm_permille_repair_20260805_r1'
$phaseDir = Join-Path $evidence $phase
New-Item -ItemType Directory -Path $phaseDir -ErrorAction Stop | Out-Null
$cl = 'D:\vs2022\VC\Tools\MSVC\14.42.34433\bin\Hostx64\x64\cl.exe'
$msvc = 'D:\vs2022\VC\Tools\MSVC\14.42.34433'
$sdk = 'D:\Windows Kits\10'
$stub = Join-Path $root 'simulation\digital_twin\tests\motor_stubs'
$motor = Join-Path $root '程序\3. 麦轮巡线小车\Hardware'
$exe = Join-Path $phaseDir 'test_motor_pwm_contract.exe'
$objectDir = $phaseDir + '\'
& $cl /nologo /TC /W4 /WX /utf-8 /D_CRT_SECURE_NO_WARNINGS `
  "/I$stub" "/I$motor" `
  "/I$msvc\include" `
  "/I$sdk\Include\10.0.22621.0\ucrt" `
  "/I$sdk\Include\10.0.22621.0\shared" `
  "/I$sdk\Include\10.0.22621.0\um" `
  (Join-Path $root 'simulation\digital_twin\tests\test_motor_pwm_contract.c') `
  (Join-Path $motor 'Motor.c') `
  "/Fo$objectDir" "/Fe$exe" `
  /link `
  "/LIBPATH:$msvc\lib\x64" `
  "/LIBPATH:$sdk\Lib\10.0.22621.0\ucrt\x64" `
  "/LIBPATH:$sdk\Lib\10.0.22621.0\um\x64"
```

Run the resulting `red/test_motor_pwm_contract.exe`.

Expected: exit code 1 and exactly the timer-period assertion fails because the observed period is 4234 instead of 999. Compilation errors, missing-path errors, or direction/CCR failures are not an acceptable RED result.

- [ ] **Step 4: Implement the minimal production change**

In `Motor.c`, add one private enum after the direction constants:

```c
enum {
    MOTOR_PWM_MAX = 999,
    MOTOR_PWM_PERIOD_COUNTS = MOTOR_PWM_MAX + 1,
    MOTOR_PWM_PRESCALER_COUNTS = 72
};
```

Replace only these literals:

```c
if (speed > MOTOR_PWM_MAX) speed = MOTOR_PWM_MAX;
if (speed < -MOTOR_PWM_MAX) speed = -MOTOR_PWM_MAX;
```

```c
t.TIM_Period = MOTOR_PWM_PERIOD_COUNTS - 1;
t.TIM_Prescaler = MOTOR_PWM_PRESCALER_COUNTS - 1;
```

Use the same two timebase expressions for TIM4. Do not touch the switch statement or any direction constant.

- [ ] **Step 5: Build and run GREEN**

Compile a fresh `green/test_motor_pwm_contract.exe` from the modified production file using the same flags and run it.

Expected: exit code 0 and `PASS test_motor_pwm_contract`.

- [ ] **Step 6: Run targeted Python safety regressions**

Run:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_runtime_protocol.py simulation/digital_twin/tests/test_frame_parser_health.py
```

Expected: all selected tests pass, exit code 0.

- [ ] **Step 7: Rebuild the locked Keil target**

First enumerate the target from the exact project, then use the `keil` skill build script to rebuild only `Target 1`:

```powershell
py -3.11 C:\Users\24668\.codex\skills\keil\scripts\keil_project.py targets --project "程序\3. 麦轮巡线小车\project.uvprojx" --json
py -3.11 C:\Users\24668\.codex\skills\keil\scripts\keil_build.py rebuild --uv4 F:\keil\UV4\UV4.exe --project "程序\3. 麦轮巡线小车\project.uvprojx" --target "Target 1" --log-dir .embeddedskills\build\v1_pwm_permille_repair_20260805_r1\keil --json
```

Expected: target enumeration contains exactly `Target 1`; rebuild reports 0 errors and 0 warnings and identifies the generated HEX/AXF paths. Do not invoke `flash`.

- [ ] **Step 8: Scope and evidence review**

Use read-only `git diff --no-index -- Motor.c.before Motor.c` plus direct reads
of the two new test files. (`git diff -- Motor.c` is insufficient because
`Motor.c` is currently untracked.) Verify the production diff contains only
the private constants, clamp literals, and two timer assignments. Record RED
output, GREEN output, pytest output, Keil JSON/log paths, and the unverified
hardware gate in a new `software_acceptance.md` inside the output directory.

Do not stage, commit, switch branches, connect hardware, or claim real-car validation.
