#ifndef _PID_H_
#define _PID_H_

#include "stdint.h"

/*============================================================================
 * PID 控制模块 v2 - 增加 Bang-Bang 混合控制 & 微分低通滤波
 *
 * 新增特性（借鉴自 SJTU-AuTop/RT1064-Code）：
 *   1. Bang-Bang + PID 混合：大误差时全力回正，小误差时 PID 精细调节
 *   2. 微分项一阶低通滤波：抑制传感器噪声对 D 项的放大
 *   3. PID_CREATE 宏：简洁的静态初始化
 *
 * 使用 Q10 定点数（实际值 × 1024），避免浮点运算
 *============================================================================*/

/* PID 场景枚举 */
typedef enum {
    PID_SCENE_NORMAL = 0,   /* 直道巡线 */
    PID_SCENE_CURVE,        /* 弯道（中等偏差） */
    PID_SCENE_SHARP,        /* 急弯 */
    PID_SCENE_LOST,         /* 失线 */
    PID_SCENE_COUNT
} PID_Scene_t;

/* PID 模式 */
typedef enum {
    PID_MODE_NORMAL = 0,    /* 标准位置式 PID */
    PID_MODE_BANGBANG,      /* Bang-Bang + PID 混合 */
} PID_Mode_t;

/* PID 参数结构体（Q10 定点格式） */
typedef struct {
    int32_t Kp;             /* 比例系数 × 1024 */
    int32_t Ki;             /* 积分系数 × 1024 */
    int32_t Kd;             /* 微分系数 × 1024 */
    int32_t i_limit;        /* 积分项限幅（原始值） */
    int32_t out_limit;      /* 输出限幅（原始值） */
    int32_t dead_zone;      /* 积分死区 */
    uint8_t smooth_coeff;   /* 输出低通滤波系数 0~10 */

    /* Bang-Bang 参数（仅 PID_MODE_BANGBANG 生效） */
    int32_t bangbang_thresh;  /* Bang-Bang 触发阈值（原始误差值） */
    int32_t bangbang_output;  /* Bang-Bang 输出值 */

    /* 微分低通滤波 */
    uint8_t derivative_lpf;   /* 微分低通系数 0~10, 0=无滤波, 10=最强滤波 */

    /* 变速积分（借鉴 Enterprise_E Changable_PID） */
    uint8_t var_integral_k;    /* 变速积分系数 0~10, 越大变化越强 */
    int32_t output_dead_zone;  /* 输出死区，|输出|<死区时输出0，消除静差 */
} PID_Param_t;

/* PID 运行时状态 */
typedef struct {
    const PID_Param_t *param;   /* 当前参数指针 */
    PID_Mode_t mode;            /* 当前模式 */
    int32_t err_now;            /* 当前误差 */
    int32_t err_last;           /* 上次误差 */
    int32_t err_sum;            /* 误差积分和 */
    int32_t derivative;         /* 原始微分项 */
    int32_t derivative_filt;    /* 滤波后微分项 */
    int32_t output;             /* 本次输出 */
    int32_t output_smooth;      /* 滤波后输出 */
    int32_t output_last;        /* 上次输出（用于增量式PID） */
    int32_t err_lastlast;       /* 上上次输出（用于增量式PID） */
} PID_t;

/*============================================================================
 * 多场景 PID 参数组
 *============================================================================*/
extern const PID_Param_t g_pid_params[PID_SCENE_COUNT];

/* PID_CREATE 宏：简洁的静态初始化
 * 用法示例：PID_t my_pid = PID_CREATE(&g_pid_params[PID_SCENE_NORMAL]);
 */
#define PID_CREATE(param_ptr) { .param = (param_ptr), .mode = PID_MODE_NORMAL }

#ifdef __cplusplus
extern "C" {
#endif

/* PID 初始化 */
void PID_Init(PID_t *pid, const PID_Param_t *param);

/* PID 重置 */
void PID_Reset(PID_t *pid);

/* PID 单步计算：输入当前误差，返回滤波后控制量 */
int32_t PID_Calc(PID_t *pid, int32_t err);

/* PID 切换场景 */
static inline void PID_SwitchScene(PID_t *pid, PID_Scene_t scene)
{
    pid->param = &g_pid_params[scene];
}

/* PID 切换模式 */
static inline void PID_SetMode(PID_t *pid, PID_Mode_t mode)
{
    pid->mode = mode;
}

#ifdef __cplusplus
}
#endif

#endif /* _PID_H_ */
