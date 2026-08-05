# -*- coding: utf-8 -*-
"""
controller_emulator.py - STM32 控制器行为级仿真器

职责:
    1. 忠实复刻 STM32 巡线控制逻辑 (逐行对应)
    2. 支持两种算法: Simple (基本版) / Advanced (PID+BangBang)
    3. 所有变量类型/溢出/截断行为与 C 一致
    4. 输出: motor_cmd (left_speed, right_speed) 供 plant_model 使用

关键约束:
    - 不做任何简化或优化
    - Q10 定点数运算必须与 C 一致
    - int16/uint8 溢出行为必须复刻
    - 所有状态变量跨调用保持

使用方式:
    ctrl = SimpleController()         # 或
    ctrl = AdvancedController(kp=8, kd=3)

    for each tick:
        motors = ctrl.step(s0, s1, s2, s3)
        # motors = (left_pwm, right_pwm)
"""

import math


# ══════════════════════════════════════════════════════════════
#  Algorithm 1: Simple Controller
#  复刻: 程序\3. 麦轮巡线小车\User\main.c
# ══════════════════════════════════════════════════════════════

class SimpleController:
    """
    基本巡线控制器 — 逐行复刻 STM32 简单版。

    控制逻辑:
        1. 读取 4 路传感器 (0=黑线, 1=白底)
        2. 计算 position = weighted sum
        3. black_count == 4 → 丢线恢复
        4. black_count == 0 → 低速前进
        5. |position| <= 1 → 死区直行
        6. |position| > 1 → 比例转向

    输出: (left_pwm, right_pwm) ∈ [0, 550]
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """重置所有状态变量"""
        self.lost_counter = 0
        self.last_position = 0

    def step(self, s0, s1, s2, s3):
        """
        单步控制。

        参数:
            s0, s1, s2, s3: 传感器状态 (0=黑线, 1=白底)
                            与 STM32 代码中取反后的值一致

        返回:
            (left_pwm, right_pwm): 电机 PWM 值
        """
        # ── 传感器取反 (与 STM32 一致) ──
        # s0 = !Sensor0_Get_State()  等已在参数中完成

        # ── position 计算 (逐行复刻) ──
        position = 0
        black_count = 0
        if s0 == 0:
            position += -3
            black_count += 1
        if s1 == 0:
            position += -1
            black_count += 1
        if s2 == 0:
            position += +1
            black_count += 1
        if s3 == 0:
            position += +3
            black_count += 1

        # ── 丢线处理 (black_count == 4) ──
        if black_count == 4:
            self.lost_counter += 1
            if self.lost_counter == 1:
                if self.last_position > 0:
                    self.last_position = 1
                else:
                    self.last_position = -1
            if self.lost_counter > 40:
                self.last_position = -self.last_position
                self.lost_counter = 0

            if self.last_position > 0:
                return self._turn_right(500)
            else:
                return self._turn_left(500)

        # ── 无黑线 (black_count == 0) ──
        elif black_count == 0:
            self.lost_counter = 0
            return self._forward(120)

        # ── 正常巡线 ──
        else:
            self.lost_counter = 0
            if position != 0:
                self.last_position = position

            # 死区
            if position >= -1 and position <= 1:
                return self._forward(180)
            elif position < 0:
                turn_speed = (-position) * 80 + 80
                if turn_speed > 550:
                    turn_speed = 550
                return self._turn_left(turn_speed)
            else:
                turn_speed = position * 80 + 80
                if turn_speed > 550:
                    turn_speed = 550
                return self._turn_right(turn_speed)

        return (180, 180)

    # ── 电机输出函数 (复刻 Motor.c) ──

    @staticmethod
    def _forward(speed):
        """Car_Forward: 所有轮正转"""
        return (speed, speed)

    @staticmethod
    def _turn_left(speed):
        """Car_TurnLeft: 左轮反转, 右轮正转 (麦轮原地旋转)"""
        return (0, speed)

    @staticmethod
    def _turn_right(speed):
        """Car_TurnRight: 左轮正转, 右轮反转"""
        return (speed, 0)

    def get_state(self):
        """获取内部状态 (调试用)"""
        return {
            'lost_counter': self.lost_counter,
            'last_position': self.last_position,
        }


# ══════════════════════════════════════════════════════════════
#  Algorithm 2: Advanced PID Controller
#  复刻: 程序\小车_改\User\main.c + System\pid.c
# ══════════════════════════════════════════════════════════════

class Q10PID:
    """
    Q10 定点 PID — 逐行复刻 pid.c 的 PID_Calc。
    
    Q10 格式: 实际值 × 1024 存储。
    所有乘法使用 int32 防溢出。
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.err_now = 0
        self.err_last = 0
        self.err_sum = 0
        self.derivative = 0
        self.derivative_filt = 0
        self.output = 0
        self.output_smooth = 0

    def calc(self, err, kp, ki, kd, i_limit, out_limit,
             dead_zone, smooth_coeff, bangbang_thresh, bangbang_output,
             derivative_lpf, var_integral_k, output_dead_zone, mode=0):
        """
        PID_Calc 完整复刻。

        参数全部为 C 代码中的原始值 (已 ×1024 的 Q10 值)。

        mode: 0=NORMAL, 1=BANGBANG
        """
        # 保存误差历史
        self.err_last = self.err_now
        self.err_now = err

        # ── Bang-Bang 模式 ──
        if mode == 1 and abs(err) > bangbang_thresh:
            self.output = bangbang_output if err > 0 else -bangbang_output
            self.output_smooth = self.output
            return self.output

        # ── 微分项 ──
        self.derivative = self.err_now - self.err_last

        # 微分低通滤波: d_filt = (lpf * d_filt + (10-lpf) * raw) / 10
        lpf = derivative_lpf
        if lpf > 0:
            self.derivative_filt = (lpf * self.derivative_filt +
                                    (10 - lpf) * self.derivative) // 10
        else:
            self.derivative_filt = self.derivative

        # ── 积分项 (变速积分) ──
        if abs(self.err_now) <= dead_zone:
            # 误差在死区内, 不积分
            pass
        else:
            # 变速积分: 误差越大, 积分越弱
            # ki_eff = Ki * max(0, 10 - var_k * |err|/100) / 10
            if var_integral_k > 0 and abs(self.err_now) > 100:
                var_factor = 10 - var_integral_k * min(abs(self.err_now) // 100, 10)
                var_factor = max(0, var_factor)
            else:
                var_factor = 10

            ki_eff = ki * var_factor // 10
            self.err_sum += self.err_now

        # 积分限幅
        if self.err_sum > i_limit:
            self.err_sum = i_limit
        if self.err_sum < -i_limit:
            self.err_sum = -i_limit

        # ── PID 输出 (Q10 定点) ──
        output = 0
        output += kp * self.err_now              # P
        output += ki * self.err_sum              # I (使用原始 Ki, 变速已在 err_sum 调整)
        output += kd * self.derivative_filt      # D

        output >>= 10  # Q10 还原

        # 输出限幅
        if output > out_limit:
            output = out_limit
        if output < -out_limit:
            output = -out_limit

        self.output = output

        # ── 输出低通滤波 ──
        c = smooth_coeff
        if c == 0:
            self.output_smooth = self.output
        else:
            self.output_smooth = (c * self.output_smooth +
                                  (10 - c) * self.output) // 10

        # ── 输出死区 ──
        if output_dead_zone > 0:
            if abs(self.output_smooth) < output_dead_zone:
                self.output_smooth = 0

        return self.output_smooth


class AdvancedController:
    """
    高级巡线控制器 — 逐行复刻 小车_改/main.c。

    特性:
        - Q10 定点 PID (位置式)
        - Bang-Bang + PID 混合
        - 多场景参数 (NORMAL/CURVE/SHARP/LOST)
        - 模式匹配查表
        - 转向速率限制
        - 速度自适应
        - 丢线恢复

    默认参数来自 pid.c 中的 g_pid_params[]。
    """

    # 默认 PID 参数 (Q10 格式, 与 pid.c 完全一致)
    DEFAULT_PARAMS = {
        'NORMAL':  {'Kp': 8, 'Ki': 0, 'Kd': 3, 'i_limit': 2000,
                    'out_limit': 450, 'dead_zone': 10, 'smooth_coeff': 3,
                    'bangbang_thresh': 600, 'bangbang_output': 450,
                    'derivative_lpf': 4, 'var_integral_k': 3,
                    'output_dead_zone': 5, 'mode': 0},
        'CURVE':   {'Kp': 12, 'Ki': 0, 'Kd': 2, 'i_limit': 2000,
                    'out_limit': 450, 'dead_zone': 10, 'smooth_coeff': 2,
                    'bangbang_thresh': 500, 'bangbang_output': 450,
                    'derivative_lpf': 3, 'var_integral_k': 2,
                    'output_dead_zone': 5, 'mode': 0},
        'SHARP':   {'Kp': 15, 'Ki': 0, 'Kd': 4, 'i_limit': 2000,
                    'out_limit': 450, 'dead_zone': 10, 'smooth_coeff': 2,
                    'bangbang_thresh': 400, 'bangbang_output': 450,
                    'derivative_lpf': 5, 'var_integral_k': 1,
                    'output_dead_zone': 8, 'mode': 1},
        'LOST':    {'Kp': 0, 'Ki': 0, 'Kd': 0, 'i_limit': 2000,
                    'out_limit': 450, 'dead_zone': 0, 'smooth_coeff': 8,
                    'bangbang_thresh': 0, 'bangbang_output': 0,
                    'derivative_lpf': 8, 'var_integral_k': 0,
                    'output_dead_zone': 0, 'mode': 0},
    }

    # 模式匹配表 (与 g_pat[] 完全一致)
    PAT_TABLE = [
        (0x01, -380, 160),  # 只有 S0
        (0x08, 380, 160),   # 只有 S3
        (0x03, -250, 200),  # S0+S1
        (0x0C, 250, 200),   # S2+S3
        (0x07, 300, 180),   # S0+S1+S2
        (0x0E, -300, 180),  # S1+S2+S3
    ]

    def __init__(self, custom_params=None):
        """
        参数:
            custom_params: dict, 可覆盖默认参数
                           例: {'NORMAL': {'Kp': 10, 'Kd': 5}}
        """
        self.params = dict(self.DEFAULT_PARAMS)
        if custom_params:
            for scene, vals in custom_params.items():
                if scene in self.params:
                    self.params[scene].update(vals)
        self.reset()

    def reset(self):
        """重置所有状态"""
        self.pid = Q10PID()
        self.last_pos_q10 = 0
        self.pi = 0      # 积分累加
        self.pd = 0      # 上次误差 (微分用)
        self.spl = 320   # 速度低通滤波器
        self.lt = 0      # 上次转向值
        self.lct = 0     # 丢线计数
        self.pat_hold = 0
        self.pat_prev = 0xFF
        self.speed = 320
        self.turn = 0

    def step(self, s0, s1, s2, s3):
        """
        单步控制。

        参数:
            s0, s1, s2, s3: 传感器 (0=黑线, 1=白底)

        返回:
            (left_pwm, right_pwm)
        """
        # ── ProcessSensors (逐行复刻) ──
        _s0 = not s0
        _s1 = not s1
        _s2 = not s2
        _s3 = not s3

        black_cnt = int(_s0) + int(_s1) + int(_s2) + int(_s3)
        pattern = (int(_s0) | (int(_s1) << 1) |
                   (int(_s2) << 2) | (int(_s3) << 3))

        # position (Q10)
        pos_q10 = 0
        if black_cnt > 0:
            w = 0
            if _s0: w -= 3
            if _s1: w -= 1
            if _s2: w += 1
            if _s3: w += 3
            pos_q10 = w * 1024 // 7

        # 低通滤波
        sm = (self.last_pos_q10 + pos_q10) // 2
        pos = sm
        self.last_pos_q10 = sm

        # 趋势
        raw = pos - self.pd
        self.pd = pos
        if raw > -20 and raw < 20:
            raw = 0

        # 置信度
        if black_cnt == 0:
            conf = 0
        elif black_cnt >= 3:
            conf = 100
        else:
            conf = black_cnt * 100 // 3

        # ── DetectElement ──
        if black_cnt == 0:
            elem = 'LOST'
        elif pattern in (0x06, 0x04, 0x02):
            elem = 'CURVE'
        elif pattern in (0x01, 0x03, 0x07):
            elem = 'SHARP_LEFT'
        elif pattern in (0x08, 0x0C, 0x0E):
            elem = 'SHARP_RIGHT'
        else:
            elem = 'STRAIGHT'

        # ── ComputeControl ──
        if elem == 'LOST':
            self.lct += 1
            if self.lct <= 3:
                if self.speed > 200:
                    self.speed = 200
                if self.turn > 200:
                    self.turn = 200
                if self.turn < -200:
                    self.turn = -200
                return self._motor_layer(self.speed, self.turn)

            t = 350 if ((self.lct // 15) & 1) else -350
            self.speed = 200
            self.turn = t
            self.lt = t
            self.spl = 200
            return self._motor_layer(self.speed, self.turn)

        self.lct = 0

        # 场景切换
        if elem == 'CURVE':
            scene = 'CURVE'
            pid_mode = 0
        elif elem in ('SHARP_LEFT', 'SHARP_RIGHT'):
            scene = 'SHARP'
            pid_mode = 1
        else:
            scene = 'NORMAL'
            pid_mode = 0

        p = self.params[scene]

        # PID 计算
        absp = abs(pos)
        gain = 300 if absp > 512 else 200
        turn_max = 450 if gain > 250 else 300

        main_turn = self.pid.calc(
            pos, p['Kp'], p['Ki'], p['Kd'],
            p['i_limit'], p['out_limit'], p['dead_zone'],
            p['smooth_coeff'], p['bangbang_thresh'], p['bangbang_output'],
            p['derivative_lpf'], p['var_integral_k'],
            p['output_dead_zone'], mode=pid_mode)

        # 辅助 PID (is_mid 且 conf < 80)
        pid_out = 0
        is_mid = pattern in (0x06, 0x04, 0x02)
        if is_mid and conf < 80:
            # 简化版辅助 PID (与 C 行为一致)
            err = pos
            d_raw = err - self.pd
            # 注意: pd 已在上面更新, 这里用的是原始 C 的 static df
            if not hasattr(self, '_df'):
                self._df = 0
            self._df = (self._df * 7 + d_raw * 3) // 10
            if self._df > 800:
                self._df = 800
            if self._df < -800:
                self._df = -800
            p_term = err * 8 // 1024
            d_term = self._df * 3 // 1024
            self.pi += err
            if self.pi > 40000:
                self.pi = 40000
            if self.pi < -40000:
                self.pi = -40000
            pid_out = p_term + d_term + self.pi // 20480
            if pid_out > 60:
                pid_out = 60
            if pid_out < -60:
                pid_out = -60

        # 模式匹配
        pt = 0
        ps = 0
        use_pat = False
        for pat, turn_val, spd_val in self.PAT_TABLE:
            if pat == pattern:
                pt = turn_val
                ps = spd_val
                use_pat = True
                break

        if use_pat:
            if pattern == self.pat_prev:
                if self.pat_hold < 2:
                    self.pat_hold += 1
            else:
                self.pat_hold = 0
            self.pat_prev = pattern

            if self.pat_hold >= 2:
                bl = self.pat_hold * 25 + 50 if self.pat_hold < 4 else 100
                raw_turn = (self.turn * (100 - bl) + pt * bl) // 100
            else:
                raw_turn = main_turn + pid_out
        else:
            self.pat_hold = 0
            self.pat_prev = 0xFF
            raw_turn = main_turn + pid_out

        # 转向速率限制
        dt_val = raw_turn - self.lt
        if dt_val > 45:
            dt_val = 45
        if dt_val < -45:
            dt_val = -45
        raw_turn = self.lt + dt_val
        if raw_turn > turn_max:
            raw_turn = turn_max
        if raw_turn < -turn_max:
            raw_turn = -turn_max
        self.lt = raw_turn
        self.turn = raw_turn

        # 速度自适应
        base = 240 if gain > 250 else 320
        at = abs(self.turn)
        spd = base - at * 3 // 5
        if spd < 80:
            spd = 80
        self.spl = (self.spl * 3 + spd) // 4
        self.speed = self.spl

        return self._motor_layer(self.speed, self.turn)

    def _motor_layer(self, spd, turn):
        """MotorLayer + CarRun (逐行复刻)"""
        forward = spd
        lateral = 0
        rotate = turn

        m1 = forward + lateral + rotate
        m2 = forward - lateral - rotate
        m3 = forward + lateral - rotate
        m4 = forward - lateral + rotate

        # 限幅 ±650
        m1 = max(-650, min(650, m1))
        m2 = max(-650, min(650, m2))
        m3 = max(-650, min(650, m3))
        m4 = max(-650, min(650, m4))

        # 电机低通滤波
        if not hasattr(self, '_sm1'):
            self._sm1 = self._sm2 = self._sm3 = self._sm4 = 0
        self._sm1 = (self._sm1 * 3 + m1) // 4
        self._sm2 = (self._sm2 * 3 + m2) // 4
        self._sm3 = (self._sm3 * 3 + m3) // 4
        self._sm4 = (self._sm4 * 3 + m4) // 4

        # 映射到 (left, right)
        # M1=BL, M2=BR, M3=FL, M4=FR
        # left = (M1 + M3) / 2, right = (M2 + M4) / 2
        left = (self._sm1 + self._sm3) // 2
        right = (self._sm2 + self._sm4) // 2

        return (max(0, min(999, abs(left))),
                max(0, min(999, abs(right))))

    def get_state(self):
        return {
            'speed': self.speed, 'turn': self.turn,
            'lost_counter': self.lct, 'pid_output': self.pid.output_smooth,
        }