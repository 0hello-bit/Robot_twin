# -*- coding: utf-8 -*-
"""
bus_bridge.py - 虚拟设备总线 ↔ 仿真器桥接

职责:
    1. 将传感器读数从仿真器推送到 VirtualDeviceBus
    2. 将电机命令从 VirtualDeviceBus 应用到 MecanumCar
    3. 管理 STM32 控制循环的单步执行

这是 "虚拟硬件层" 的核心:
    仿真器 (传感器/小车) ←→ VirtualDeviceBus ←→ STM32 兼容代码

传感器映射说明:
    仿真器约定: 0=检测到黑线, 1=白底
    STM32 GPIO 约定 (TCRT5000 + 上拉): 1=黑线(HIGH), 0=白底(LOW)
    STM32 C 代码: s0 = !Sensor_Get_State(); if(s0==0) → on black

    本桥接器在推送传感器时进行极性转换,
    使 VirtualDeviceBus 中的值与真实 GPIO 行为一致。
"""


class BusBridge:
    """
    设备总线桥接器。
    
    连接仿真器的物理实体 (MecanumCar + SensorArray)
    与虚拟硬件总线 (VirtualDeviceBus)，
    使 STM32 兼容代码可以像操作真实硬件一样控制仿真器。
    """

    def __init__(self, bus, car, sensor_array, track_map):
        """
        参数:
            bus:          VirtualDeviceBus 实例
            car:          MecanumCar 实例
            sensor_array: SensorArray 实例
            track_map:    TrackMap 实例
        """
        self.bus = bus
        self.car = car
        self.sensor_array = sensor_array
        self.track_map = track_map

    @staticmethod
    def _sim_to_gpio(sim_states):
        """
        仿真器传感器状态 → 真实 GPIO 状态。
        
        仿真器: 0=on track (black), 1=off track (white)
        GPIO:   1=on black (HIGH, 无反射), 0=off track (LOW, 有反射)
        
        TCRT5000 + 上拉电阻:
            白色表面 → 强反射 → 光电管导通 → 输出 LOW (0)
            黑色表面 → 无反射 → 光电管截止 → 上拉 HIGH (1)
        """
        return [1 - s for s in sim_states]

    def push_sensors(self):
        """
        从仿真器读取传感器状态, 转换极性后推送到虚拟设备总线。
        
        流程:
            1. 更新传感器世界坐标
            2. 读取传感器状态 (仿真器约定: 0=黑线, 1=白底)
            3. 转换为 GPIO 约定 (1=黑线, 0=白底)
            4. 推送到 VirtualDeviceBus
        """
        self.sensor_array.update_positions(self.car)
        sim_states = self.sensor_array.read(self.track_map)
        gpio_states = self._sim_to_gpio(sim_states)
        self.bus.set_all_sensors(gpio_states)
        return sim_states  # 返回仿真器约定的状态 (供 UI 使用)

    def push_sensors_with_noise(self, noise_model):
        """
        读取传感器并注入噪声, 再推送到总线。
        
        参数:
            noise_model: WorldNoiseModel 实例
        """
        self.sensor_array.update_positions(self.car)
        sim_states = self.sensor_array.read(self.track_map)
        positions = self.sensor_array.get_positions()
        noisy_sim = noise_model.apply_sensor_noise(sim_states, positions, self.track_map)
        gpio_states = self._sim_to_gpio(noisy_sim)
        self.bus.set_all_sensors(gpio_states)
        return noisy_sim  # 返回仿真器约定的状态

    def pull_motors(self):
        """
        从虚拟设备总线读取电机命令, 应用到 MecanumCar。
        
        流程:
            1. 读取 4 个电机的 (direction, speed)
            2. 调用 car.motors[i].set_speed() 设置速度
            3. 返回电机状态供调试
        """
        motor_states = self.bus.get_all_motors()
        for i, (direction, speed) in enumerate(motor_states):
            self.car.motors[i].set_speed(direction, speed)
        return motor_states

    def pull_motors_normalized(self):
        """
        从总线读取电机并返回归一化速度列表 (用于 UI 显示)。
        
        返回:
            list[float]: 4 个轮子的归一化速度 (-1 ~ +1)
        """
        motor_states = self.bus.get_all_motors()
        speeds = []
        for direction, speed in motor_states:
            if direction == 0:
                speeds.append(speed / 999.0)
            else:
                speeds.append(-speed / 999.0)
        return speeds

    def stop_all(self):
        """停止所有电机 (通过总线)"""
        self.bus.stop_all_motors()
        self.pull_motors()

    def advance_tick(self, dt_ms):
        """推进 MCU 时钟"""
        self.bus.advance_tick(dt_ms)

    def get_delay_ms(self):
        """获取最近一次 Delay_ms 调用值"""
        return self.bus.get_delay_value()
