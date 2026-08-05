# -*- coding: utf-8 -*-
"""
stm32_faithful_controller.py — STM32 巡线控制逻辑的忠实 Python 移植。

==============================================================================
本控制器 1:1 对齐真车权威代码：
    程序/小车_改/User/main.c   (已现实验证可正常巡线)
    == 程序/3. 麦轮巡线小车/User/main.c 的巡线算法逐行相同
==============================================================================

【重要修正记录】
旧版本本文件移植的是 程序/小车_改/System/pid.c 里的「多场景 Bang-Bang PID」
(Kp=8/12/15、积分、Q10 定点)。但那段代码是**死代码**——main.c 从未调用它，
Keil 链接器 map 文件 (Listings/Car_Modified.map) 明确写着:
    Removing pid.o(i.PID_Calc), (390 bytes).
    Removing pid.o(i.PID_Init), (26 bytes).
即真车上**根本没跑过 pid.c**。真车真正运行的是 main.c 里内联实现的纯 PD 算法。
本文件现已改为忠实复刻 main.c 的内联算法，使数字孪生与真车行为一致。

【关键对应关系】
- 极性:仿真传感器 0=黑线/1=白底;真车 main.c 用 `b=!SensorGet()`，b=1 表示压在线上。
        移植时把仿真值翻转回真车语义: b = 1 if sensor==0 else 0
- 输出:真车 MotorOut 输出 PWM(约 -650~650);仿真 car.drive 要求归一化 -1~+1，
        因此 motor_cmd = (sm_l/MOTOR_LIMIT, sm_r/MOTOR_LIMIT)。
- 电机映射:真车 左轮=M1+M4、右轮=M2+M3，差速驱动(巡线时未用麦轮横移)。
- 主循环:真车每帧 Delay 5ms;仿真按 dt 调用，本算法与 dt 无关(纯离散步进)。

所有常量均直接取自 小车_改/main.c 的 #define，改参数时与 C 端一一对应。
"""

from control.base_controller import BaseController, ControllerOutput


class STM32FaithfulController(BaseController):
    """忠实复刻 小车_改/main.c 内联巡线算法的控制器。"""

    # ── PID 参数 (main.c: PID_KP / PID_KD) ──
    PID_KP            = 35.0    # 比例系数
    PID_KD            = 10.0    # 微分系数 (纯 PD，无积分)

    # ── 动态速度参数 ──
    SPEED_MAX         = 680     # 最大速度 (直道)
    SPEED_MIN         = 260     # 最小速度 (弯道)
    SPEED_ERR_DECAY   = 22.0    # 误差每增大 1.0，速度衰减值
    SPEED_INIT        = 400.0   # 速度平滑滤波初始值

    # ── 转向量限幅 ──
    TURN_LIMIT        = 600     # PID 转向量上限

    # ── 单传感器压线时的固定误差 ──
    ERR_OUTER         = 2.5     # 最外侧传感器压线误差
    ERR_INNER         = 0.45    # 内侧传感器压线误差

    # ── 弯道增益 ──
    TURN_GAIN_K       = 0.9     # 偏差越大转向越强

    # ── 平滑滤波系数 (旧值权重 / 新值权重) ──
    ERR_FILTER_OLD    = 0.65;  ERR_FILTER_NEW   = 0.35
    SPEED_FILTER_OLD  = 0.75;  SPEED_FILTER_NEW = 0.25
    TURN_FILTER_OLD   = 0.55;  TURN_FILTER_NEW  = 0.45
    MOTOR_FILTER_OLD  = 0.15;  MOTOR_FILTER_NEW = 0.85

    # ── 急弯强制转向 ──
    CURVE_INNER_REVERSE     = -260
    CURVE_MIN_TURN_EXTRA    = 60
    CURVE_MID_INNER_REVERSE = -120
    CURVE_MID_TURN_EXTRA    = 20

    # ── 传感器 pattern (位序 b0 b1 b2 b3 → bit3 bit2 bit1 bit0) ──
    PATTERN_LEFT_OUTER  = 0x08   # 1000 最左压线
    PATTERN_LEFT_HEAVY  = 0x0C   # 1100 左侧重压
    PATTERN_LEFT_INNER  = 0x04   # 0100 左中压线
    PATTERN_RIGHT_INNER = 0x02   # 0010 右中压线
    PATTERN_RIGHT_HEAVY = 0x03   # 0011 右侧重压
    PATTERN_RIGHT_OUTER = 0x01   # 0001 最右压线

    # ── 其他 ──
    D_LIMIT             = 0.8    # 微分项变化限幅
    SENSOR_STABLE_COUNT = 0      # 去抖阈值 (0 = 每帧即生效)
    LOST_HOLD_COUNT     = 3      # 丢线后保持上次输出的帧数
    LOST_FAST_OUTER     = 600    # 丢线找线:外侧轮速
    LOST_FAST_INNER     = -200   # 丢线找线:内侧轮速 (负=后退)
    MOTOR_LIMIT         = 650    # 电机 PWM 绝对值上限

    def __init__(self):
        super().__init__()
        self.reset()

    # ------------------------------------------------------------------ #
    def reset(self):
        # 对应 main.c 主函数里的局部状态变量
        self._last_err      = 0.0
        self._last_dir      = 1
        self._lost_step     = 0
        self._sm_err        = 0.0
        self._sm_speed      = self.SPEED_INIT
        self._sm_turn       = 0.0
        self._last_pattern  = 0
        self._stable_pattern = 0
        self._same_count    = 0
        # 对应 MotorOut 里的 static sm_l / sm_r
        self._sm_l          = 0.0
        self._sm_r          = 0.0
        # 诊断 / UI 暴露字段
        self.position       = 0.0
        self.black_count    = 0
        self.pid_output     = 0.0
        self.motor_cmd      = (0.0, 0.0)
        self.element_type   = "LINE"

    # ------------------------------------------------------------------ #
    @staticmethod
    def _clamp(v, lo, hi):
        if v > hi:
            return hi
        if v < lo:
            return lo
        return v

    def _motor_out(self, left, right):
        """对应 main.c 的 MotorOut(l, r):限幅 → 电机平滑 → 归一化输出。"""
        left  = self._clamp(int(left),  -self.MOTOR_LIMIT, self.MOTOR_LIMIT)
        right = self._clamp(int(right), -self.MOTOR_LIMIT, self.MOTOR_LIMIT)
        self._sm_l = self._sm_l * self.MOTOR_FILTER_OLD + left  * self.MOTOR_FILTER_NEW
        self._sm_r = self._sm_r * self.MOTOR_FILTER_OLD + right * self.MOTOR_FILTER_NEW
        ln = max(-1.0, min(1.0, self._sm_l / self.MOTOR_LIMIT))
        rn = max(-1.0, min(1.0, self._sm_r / self.MOTOR_LIMIT))
        self.motor_cmd = (ln, rn)

    # ------------------------------------------------------------------ #
    def update(self, sensor_input, dt):
        out = ControllerOutput()
        out.sensor_reading = list(sensor_input)

        # 仿真 0=黑线/1=白底  →  真车 b=1=压线
        b0 = 1 if sensor_input[0] == 0 else 0
        b1 = 1 if sensor_input[1] == 0 else 0
        b2 = 1 if sensor_input[2] == 0 else 0
        b3 = 1 if sensor_input[3] == 0 else 0
        pattern = (b0 << 3) | (b1 << 2) | (b2 << 1) | b3

        # 传感器模式去抖 (SENSOR_STABLE_COUNT=0 时每帧直接生效)
        if pattern == self._last_pattern:
            if self._same_count < 5:
                self._same_count += 1
        else:
            self._same_count = 0
            self._last_pattern = pattern
        if self._same_count >= self.SENSOR_STABLE_COUNT:
            self._stable_pattern = pattern

        sp = self._stable_pattern
        b0 = (sp >> 3) & 1
        b1 = (sp >> 2) & 1
        b2 = (sp >> 1) & 1
        b3 = sp & 1

        black = b0 + b1 + b2 + b3
        pos = 0
        if b0: pos -= 3
        if b1: pos -= 1
        if b2: pos += 1
        if b3: pos += 3

        # ===== 丢线处理 =====
        if black == 0:
            self._lost_step += 1
            if self._lost_step < self.LOST_HOLD_COUNT:
                self._motor_out(self._sm_l, self._sm_r)          # 保持上次输出
            elif self._last_dir > 0:
                self._motor_out(self.LOST_FAST_OUTER, self.LOST_FAST_INNER)
            else:
                self._motor_out(self.LOST_FAST_INNER, self.LOST_FAST_OUTER)
            self.black_count = 0
            self.pid_output = 0.0
            self.element_type = "LOST"
            out.left_speed, out.right_speed = self.motor_cmd
            out.error = self.position
            return out

        self._lost_step = 0

        # ===== 误差计算 (三分支) =====
        if black == 4:
            error = self._sm_err                       # 全压线:沿用上次
        elif black == 1:
            if   b0: error = -self.ERR_OUTER
            elif b1: error = -self.ERR_INNER
            elif b2: error =  self.ERR_INNER
            else:    error =  self.ERR_OUTER
        else:
            error = pos / black

        # 误差平滑
        self._sm_err = self._sm_err * self.ERR_FILTER_OLD + error * self.ERR_FILTER_NEW
        error = self._sm_err

        # 微分 + 限幅
        d = error - self._last_err
        if d > self.D_LIMIT:  d = self.D_LIMIT
        if d < -self.D_LIMIT: d = -self.D_LIMIT
        self._last_err = error

        abs_error = abs(error)
        turn_gain = 1.0 + abs_error * self.TURN_GAIN_K
        pid = (self.PID_KP * error + self.PID_KD * d) * turn_gain

        # 动态速度
        target_speed = int(self.SPEED_MAX - abs_error * self.SPEED_ERR_DECAY)
        target_speed = self._clamp(target_speed, self.SPEED_MIN, self.SPEED_MAX)
        target_turn  = self._clamp(int(pid), -self.TURN_LIMIT, self.TURN_LIMIT)

        # 速度 / 转向平滑
        self._sm_speed = self._sm_speed * self.SPEED_FILTER_OLD + target_speed * self.SPEED_FILTER_NEW
        self._sm_turn  = self._sm_turn  * self.TURN_FILTER_OLD  + target_turn  * self.TURN_FILTER_NEW

        speed = int(self._sm_speed)
        turn  = int(self._sm_turn)
        curve_reverse = 0

        # ===== 急弯强制转向 (switch stable_pattern) =====
        if sp in (self.PATTERN_LEFT_OUTER, self.PATTERN_LEFT_HEAVY):
            curve_reverse = 1
            speed = self.SPEED_MIN
            force_turn = speed - self.CURVE_INNER_REVERSE + self.CURVE_MIN_TURN_EXTRA
            turn = -force_turn
        elif sp == self.PATTERN_LEFT_INNER:
            curve_reverse = 1
            speed = self.SPEED_MIN
            force_turn = speed - self.CURVE_MID_INNER_REVERSE + self.CURVE_MID_TURN_EXTRA
            turn = -force_turn
        elif sp == self.PATTERN_RIGHT_INNER:
            curve_reverse = 1
            speed = self.SPEED_MIN
            force_turn = speed - self.CURVE_MID_INNER_REVERSE + self.CURVE_MID_TURN_EXTRA
            turn = force_turn
        elif sp in (self.PATTERN_RIGHT_HEAVY, self.PATTERN_RIGHT_OUTER):
            curve_reverse = 1
            speed = self.SPEED_MIN
            force_turn = speed - self.CURVE_INNER_REVERSE + self.CURVE_MIN_TURN_EXTRA
            turn = force_turn

        # 差速分配
        left  = speed + turn
        right = speed - turn
        if curve_reverse:
            left  = self._clamp(left,  self.CURVE_INNER_REVERSE, self.MOTOR_LIMIT)
            right = self._clamp(right, self.CURVE_INNER_REVERSE, self.MOTOR_LIMIT)
        else:
            left  = self._clamp(left,  20, self.MOTOR_LIMIT)
            right = self._clamp(right, 20, self.MOTOR_LIMIT)

        if pos != 0:
            self._last_dir = 1 if pos > 0 else -1

        self._motor_out(left, right)

        # 诊断 / UI
        self.position     = error
        self.black_count  = black
        self.pid_output   = pid
        self.element_type = "CURVE" if curve_reverse else "LINE"
        out.left_speed, out.right_speed = self.motor_cmd
        out.raw_pid = pid
        out.error   = error
        return out

    # ------------------------------------------------------------------ #
    def get_name(self):
        return "LineFollow-Faithful(小车_改/main.c)"

    def get_params(self):
        return {
            "Kp": self.PID_KP, "Kd": self.PID_KD,
            "position": round(self.position, 3),
            "black": self.black_count,
            "element": self.element_type,
        }
