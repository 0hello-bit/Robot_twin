#include "pid.h"

/*============================================================================
 * 多场景 PID 参数（Q10 格式：实际值 × 1024）
 *
 * 各场景参数设计意图：
 *   直道：Kp较小，Kd略大 → 稳定循线，抑制过冲
 *   弯道：Kp增大，Kd略减 → 快速响应弯道
 *   急弯：Bang-Bang 模式 + 大 Kp → 紧急转向不丢失
 *   失线：输出保持柔和过渡
 *============================================================================*/
const PID_Param_t g_pid_params[PID_SCENE_COUNT] = {
    /* PID_SCENE_NORMAL — 直道循线 */
    {
        .Kp               = 8    * 1024 / 1024,
        .Ki               = 0    * 1024 / 1024,
        .Kd               = 3    * 1024 / 1024,
        .i_limit          = 2000,
        .out_limit        = 450,
        .dead_zone        = 10,
        .smooth_coeff     = 3,
        .bangbang_thresh  = 600,
        .bangbang_output  = 450,
        .derivative_lpf   = 4,             /* 中等微分滤波 */
        .var_integral_k   = 3,             /* 变速积分，中等 */
        .output_dead_zone = 5,             /* 消除小静差 */
    },
    /* PID_SCENE_CURVE — 弯道 */
    {
        .Kp               = 12   * 1024 / 1024,
        .Ki               = 0    * 1024 / 1024,
        .Kd               = 2    * 1024 / 1024,
        .i_limit          = 2000,
        .out_limit        = 450,
        .dead_zone        = 10,
        .smooth_coeff     = 2,
        .bangbang_thresh  = 500,
        .bangbang_output  = 450,
        .derivative_lpf   = 3,             /* 稍弱滤波，响应更快 */
        .var_integral_k   = 2,             /* 弭道变速积分弱 */
        .output_dead_zone = 5,             /* 消除小静差 */
    },
    /* PID_SCENE_SHARP — 急弯 */
    {
        .Kp               = 15   * 1024 / 1024,
        .Ki               = 0    * 1024 / 1024,
        .Kd               = 4    * 1024 / 1024,
        .i_limit          = 2000,
        .out_limit        = 450,
        .dead_zone        = 10,
        .smooth_coeff     = 2,
        .bangbang_thresh  = 400,           /* 急弯时更容易触发 Bang-Bang */
        .bangbang_output  = 450,
        .derivative_lpf   = 5,             /* 较强滤波，急弯噪声大 */
        .var_integral_k   = 1,             /* 急弯变速积分最弱 */
        .output_dead_zone = 8,             /* 急弯允许稍大静差 */
    },
    /* PID_SCENE_LOST — 失线 */
    {
        .Kp               = 0,
        .Ki               = 0,
        .Kd               = 0,
        .i_limit          = 2000,
        .out_limit        = 450,
        .dead_zone        = 0,
        .smooth_coeff     = 8,
        .bangbang_thresh  = 0,
        .bangbang_output  = 0,
        .derivative_lpf   = 8,
        .var_integral_k   = 0,             /* 失线不变速积分 */
        .output_dead_zone = 0,
    },
};

/*============================================================================
 * PID_Init
 *============================================================================*/
void PID_Init(PID_t *pid, const PID_Param_t *param)
{
    pid->param          = param;
    pid->mode           = PID_MODE_NORMAL;
    pid->err_now        = 0;
    pid->err_last       = 0;
    pid->err_sum        = 0;
    pid->derivative     = 0;
    pid->derivative_filt = 0;
    pid->output         = 0;
    pid->output_smooth  = 0;
    pid->output_last    = 0;
    pid->err_lastlast   = 0;
}

/*============================================================================
 * PID_Reset
 *============================================================================*/
void PID_Reset(PID_t *pid)
{
    pid->err_now        = 0;
    pid->err_last       = 0;
    pid->err_sum        = 0;
    pid->derivative     = 0;
    pid->derivative_filt = 0;
    pid->output         = 0;
    pid->output_smooth  = 0;
    pid->output_last    = 0;
    pid->err_lastlast   = 0;
}

/*============================================================================
 * PID_Calc
 *   位置式 PID + Bang-Bang 混合 + 微分低通滤波 + 积分分离 + 输出低通滤波
 *
 *   控制策略（借鉴 SJTU-AuTop BangBang PID 思路）：
 *     大误差（> bangbang_thresh）：Bang-Bang → 全力回正，快速纠偏
 *     小误差（<= bangbang_thresh）：位置式 PID → 精细调节
 *
 *   微分低通滤波（一阶滞后）：
 *     d_filt = (lpf * d_filt + (10-lpf) * raw_d) / 10
 *     有效抑制传感器噪声对 D 项的放大
 *
 *   积分分离：
 *     |err| > dead_zone 时不积分，防饱和
 *
 *   输出低通滤波：
 *     out_smooth = (coeff * out_smooth + (10-coeff) * output) / 10
 *============================================================================*/
int32_t PID_Calc(PID_t *pid, int32_t err)
{
    const PID_Param_t *p = pid->param;

    /* 保存误差历史 */
    pid->err_last = pid->err_now;
    pid->err_now  = err;

    int32_t abs_err = (err > 0) ? err : -err;

    /* === Bang-Bang / PID 模式选择 === */
    if (pid->mode == PID_MODE_BANGBANG && abs_err > p->bangbang_thresh) {
        /* Bang-Bang：大误差时全力输出 */
        pid->output = (err > 0) ? p->bangbang_output : -p->bangbang_output;
        /* Bang-Bang 期间不积分、不积累微分历史 */
        pid->err_sum = 0;
        pid->derivative_filt = 0;
    } else {
        /* === 积分分离 === */
        if (abs_err < p->dead_zone) {
            pid->err_sum += err;
            if (pid->err_sum > p->i_limit)  pid->err_sum = p->i_limit;
            if (pid->err_sum < -p->i_limit) pid->err_sum = -p->i_limit;
        }

        /* 变速积分（借鉴 Enterprise_E） */
        int32_t ki_eff = (int32_t)p->Ki;
        if (p->var_integral_k > 0 && abs_err > 300) {
            int32_t reduce = abs_err * p->var_integral_k / 1024;
            if (reduce > p->Ki) reduce = p->Ki;
            ki_eff = p->Ki - reduce;
        }

        /* === 原始微分 === */
        pid->derivative = pid->err_now - pid->err_last;

        /* === 微分低通滤波（一阶滞后） === */
        uint8_t dlpf = p->derivative_lpf;
        if (dlpf == 0) {
            pid->derivative_filt = pid->derivative;
        } else {
            pid->derivative_filt = (dlpf * pid->derivative_filt
                                  + (10 - dlpf) * pid->derivative) / 10;
        }

        /* === 位置式 PID === */
        int32_t output = 0;
        output += (int32_t)p->Kp * pid->err_now;               /* P */
        output += (int32_t)ki_eff * pid->err_sum;               /* I（变速积分） */
        output += (int32_t)p->Kd * pid->derivative_filt;        /* D（使用滤波后的值） */

        /* Q10 定点还原 */
        output >>= 10;

        /* 输出限幅 */
        if (output > p->out_limit)  output = p->out_limit;
        if (output < -p->out_limit) output = -p->out_limit;

        pid->output = output;
    }

    /* === 输出低通滤波（一阶滞后） === */
    uint8_t c = p->smooth_coeff;
    if (c == 0) {
        pid->output_smooth = pid->output;
    } else {
        pid->output_smooth = (c * pid->output_smooth + (10 - c) * pid->output) / 10;
    }

    /* ═══ 输出死区（消除静差）═══ */
    if (p->output_dead_zone > 0) {
        int32_t abs_out = (pid->output_smooth > 0) ? pid->output_smooth : -pid->output_smooth;
        if (abs_out < p->output_dead_zone) {
            pid->output_smooth = 0;
        }
    }

    return pid->output_smooth;
}
