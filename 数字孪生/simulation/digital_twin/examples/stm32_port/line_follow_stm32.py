# -*- coding: utf-8 -*-
"""
line_follow_stm32.py - STM32 巡线控制逻辑 (Python 移植版)

源文件: 程序/3. 麦轮巡线小车/User/main.c

移植原则:
    1. 保持与 C 代码相同的控制算法和决策逻辑
    2. 传感器读取通过 hal_stubs 调用 (与真实 STM32 一致)
    3. 电机输出适配仿真器的差速驱动接口
    4. 控制决策 (position / black_count / lost_counter) 完全保留

传感器映射:
    S0(PB1) = 最左侧
    S1(PB0) = 左中
    S2(PB4) = 右中
    S3(PB5) = 最右侧

控制逻辑:
    1. 读取 4 路传感器
    2. 计算位置偏差 position
    3. 根据 black_count 和 position 决定运动:
       - black_count == 4: 出线, 按最后方向旋转找回
       - black_count == 0: 全白, 低速直行
       - else: 根据偏差大小决定直行或转向
    4. 延时 30ms

电机接口说明:
    本控制器通过 get_motor_command() 返回差速指令 (left, right)，
    由仿真器的 car.drive() 执行。
    这保留了 STM32 的控制算法，同时适配仿真器的运动学模型。
"""

from stm32_compat import hal_stubs as hal


class STM32LineFollowController:
    """
    STM32 兼容巡线控制器。
    
    控制算法完全移植自 main.c。
    电机输出适配仿真器的 car.drive(left, right) 接口。
    """

    def __init__(self):
        # ── 控制变量 (与 C 代码一一对应) ──
        self.position = 0           # int16_t position
        self.s0 = 0                 # uint8_t s0
        self.s1 = 0                 # uint8_t s1
        self.s2 = 0                 # uint8_t s2
        self.s3 = 0                 # uint8_t s3
        self.black_count = 0        # uint8_t black_count
        self.turn_speed = 0         # uint16_t turn_speed
        self.lost_counter = 0       # uint16_t lost_counter
        self.last_position = 0      # int16_t last_position

        # ── 电机输出 ──
        self._left_speed = 0.0
        self._right_speed = 0.0

        # ── 诊断信息 (Python 扩展) ──
        self._tick_count = 0
        self._motor_output = (0.0, 0.0)
        self._sensor_reading = [1, 1, 1, 1]
        self._error = 0.0

    def begin(self):
        """初始化硬件"""
        hal.NVIC_PriorityGroupConfig(hal.NVIC_PriorityGroup_2)
        hal.Sensor_Init()
        hal.Motor_Init()

    def reset(self):
        """重置控制器内部状态"""
        self.position = 0
        self.s0 = self.s1 = self.s2 = self.s3 = 0
        self.black_count = 0
        self.turn_speed = 0
        self.lost_counter = 0
        self.last_position = 0
        self._left_speed = 0.0
        self._right_speed = 0.0
        self._tick_count = 0
        self._motor_output = (0.0, 0.0)
        self._sensor_reading = [1, 1, 1, 1]
        self._error = 0.0

    def run_one_tick(self):
        """
        执行一个控制周期。
        
        保留 main.c 的完整控制算法:
        - 传感器读取
        - 位置计算
        - 运动决策 (直行/转向/出线恢复)
        
        电机输出转换为差速指令 (left, right)，
        由外部通过 get_motor_command() 获取并执行。
        """
        # ── 1. 读取传感器 ──
        # C 代码: s0 = !Sensor0_Get_State(); (取反: 0=黑线, 1=白底)
        self.s0 = not hal.Sensor0_Get_State()
        self.s1 = not hal.Sensor1_Get_State()
        self.s2 = not hal.Sensor2_Get_State()
        self.s3 = not hal.Sensor3_Get_State()

        # ── 2. 计算位置偏差 ──
        self.position = 0
        self.black_count = 0

        if self.s0 == 0:
            self.position += -3
            self.black_count += 1
        if self.s1 == 0:
            self.position += -1
            self.black_count += 1
        if self.s2 == 0:
            self.position += 1
            self.black_count += 1
        if self.s3 == 0:
            self.position += 3
            self.black_count += 1

        # ── 3. 运动控制决策 (与 main.c 完全一致) ──
        if self.black_count == 4:
            # 出线恢复逻辑
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
                # C: Car_TurnRight(500)
                self._set_turn_right(500)
            else:
                # C: Car_TurnLeft(500)
                self._set_turn_left(500)

        elif self.black_count == 0:
            # 全白: 低速直行
            self.lost_counter = 0
            # C: Car_Forward(120)
            self._set_forward(120)

        else:
            # 正常巡线
            self.lost_counter = 0

            if self.position != 0:
                self.last_position = self.position

            if self.position >= -1 and self.position <= 1:
                # 偏差小 → 直行
                # C: Car_Forward(180)
                self._set_forward(180)

            elif self.position < 0:
                # 明显偏左 → 左转
                # C: turn_speed = (-position) * 80 + 80; Car_TurnLeft(turn_speed)
                turn_speed = (-self.position) * 80 + 80
                if turn_speed > 550:
                    turn_speed = 550
                self._set_turn_left(turn_speed)

            else:
                # 明显偏右 → 右转
                # C: turn_speed = position * 80 + 80; Car_TurnRight(turn_speed)
                turn_speed = self.position * 80 + 80
                if turn_speed > 550:
                    turn_speed = 550
                self._set_turn_right(turn_speed)

        # ── 4. 更新诊断信息 ──
        self._error = float(self.position)
        self._sensor_reading = [
            0 if self.s0 else 1,
            0 if self.s1 else 1,
            0 if self.s2 else 1,
            0 if self.s3 else 1,
        ]
        self._motor_output = (self._left_speed, self._right_speed)
        self._tick_count += 1

    # ── 电机输出函数 ──
    # 将 C 代码的 Car_Forward/TurnLeft/TurnRight 转换为差速指令
    # 保持与真实小车相同的转向比例关系

    def _set_forward(self, speed):
        """
        前进: 左右轮同速。
        对应 C: Car_Forward(speed)
        """
        norm = speed / 999.0
        self._left_speed = norm
        self._right_speed = norm

    def _set_turn_left(self, speed):
        """
        左转: 右轮快, 左轮慢 (差速转向)。
        对应 C: Car_TurnLeft(speed)
        
        在真实麦轮小车上, Car_TurnLeft 产生旋转运动。
        在仿真器中, 通过差速实现相同效果:
            左轮 = 基础速度 - 转向分量
            右轮 = 基础速度 + 转向分量
        """
        base = 0.08  # 基础前进速度 (保持前进)
        turn = (speed / 999.0) * 0.5  # 转向分量
        self._left_speed = max(-1.0, min(1.0, base - turn))
        self._right_speed = max(-1.0, min(1.0, base + turn))

    def _set_turn_right(self, speed):
        """
        右转: 左轮快, 右轮慢 (差速转向)。
        对应 C: Car_TurnRight(speed)
        """
        base = 0.08
        turn = (speed / 999.0) * 0.5
        self._left_speed = max(-1.0, min(1.0, base + turn))
        self._right_speed = max(-1.0, min(1.0, base - turn))

    def get_motor_command(self):
        """
        获取差速电机指令。
        
        返回:
            (left_speed, right_speed): 归一化速度 (-1 ~ +1)
            用于 car.drive(left, right)
        """
        return self._left_speed, self._right_speed

    def get_name(self):
        return "STM32_Compat(line_follow)"

    def get_params(self):
        return {
            'mode': 'stm32_port',
            'algorithm': 'proportional_turn',
            'base_speed_forward': 180,
            'base_speed_lost': 120,
            'turn_gain': 80,
            'turn_max': 550,
        }

    def get_diagnostic(self):
        return {
            'tick_count': self._tick_count,
            'position': self.position,
            'black_count': self.black_count,
            'lost_counter': self.lost_counter,
            'last_position': self.last_position,
            'motor_output': self._motor_output,
            'sensor_reading': self._sensor_reading,
            'error': self._error,
        }
