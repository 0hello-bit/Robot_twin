# -*- coding: utf-8 -*-
"""
stm32_controller.py - STM32 巡线逻辑 Python 单源移植

逐行移植自: 程序/3. 麦轮巡线小车/User/main.c
不做任何优化, 不加 PID, 保持与 C 代码行为级一致。

C 代码核心逻辑:
  1. 读 4 路传感器 (0=黑线, 1=白底)
  2. position = 加权偏差 (S0=-3, S1=-1, S2=+1, S3=+3)
  3. black_count = 检测到黑线的传感器数
  4. 决策:
     - black_count == 4: 丢线, 根据 last_position 方向找线
     - black_count == 0: 全白, 直行 (PWM 120)
     - 正常:
       - |position| <= 1: 死区直行 (PWM 180)
       - position < 0: 左转, speed = |position|*80+80 (max 550)
       - position > 0: 右转, speed = position*80+80 (max 550)
  5. Delay_ms(30)

注意: C 代码中 Car_TurnLeft/Right(speed) 是差速控制:
  TurnLeft:  M1 fwd, M2 back, M3 back, M4 fwd  → 左轮正, 右轮反
  TurnRight: M1 back, M2 fwd, M3 fwd, M4 back  → 左轮反, 右轮正
  Forward:   全部正转

Python 移植保持完全相同的决策逻辑和 PWM 计算。
"""

from control.base_controller import ControllerOutput


class STM32LineFollowController:
    """
    STM32 巡线控制器 (Python 单源移植)。

    逐行对应 main.c 中的巡线逻辑。
    """

    WEIGHTS = [-3.0, -1.0, 1.0, 3.0]

    def __init__(self):
        self.last_position = 0
        self.lost_counter = 0

    def update(self, sensor_input, dt=None):
        """
        执行一步巡线控制。

        参数:
            sensor_input: [S0, S1, S2, S3], 0=黑线, 1=白底
            dt:           忽略 (STM32 用固定 30ms 延迟)

        返回:
            ControllerOutput: left_speed, right_speed 归一化 (-1~1)
        """
        s0, s1, s2, s3 = sensor_input[0], sensor_input[1], sensor_input[2], sensor_input[3]

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

        out = ControllerOutput()
        out.sensor_reading = list(sensor_input)
        out.error = float(position)

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
                self._turn_right(out, 500)
            else:
                self._turn_left(out, 500)

        elif black_count == 0:
            self.lost_counter = 0
            self._forward(out, 120)

        else:
            self.lost_counter = 0
            if position != 0:
                self.last_position = position
            if -1 <= position <= 1:
                self._forward(out, 180)
            elif position < 0:
                turn_speed = int((-position) * 80 + 80)
                if turn_speed > 550:
                    turn_speed = 550
                self._turn_left(out, turn_speed)
            else:
                turn_speed = int(position * 80 + 80)
                if turn_speed > 550:
                    turn_speed = 550
                self._turn_right(out, turn_speed)

        out.metadata['source'] = 'stm32_port'
        out.metadata['position'] = position
        out.metadata['black_count'] = black_count
        return out

    def _forward(self, out, speed):
        norm = speed / 999.0
        out.left_speed = norm
        out.right_speed = norm
        out.raw_pid = 0.0

    def _turn_left(self, out, speed):
        norm = speed / 999.0
        out.left_speed = -norm
        out.right_speed = norm
        out.raw_pid = -norm

    def _turn_right(self, out, speed):
        norm = speed / 999.0
        out.left_speed = norm
        out.right_speed = -norm
        out.raw_pid = norm

    def reset(self):
        self.last_position = 0
        self.lost_counter = 0

    def get_name(self):
        return "STM32_Port(main.c)"

    def get_params(self):
        return {'type': 'stm32_direct_control', 'deadzone': 1, 'gain': 80}
