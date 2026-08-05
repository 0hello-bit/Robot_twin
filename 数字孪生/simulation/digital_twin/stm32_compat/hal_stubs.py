# -*- coding: utf-8 -*-
"""
hal_stubs.py - STM32 HAL 函数桩 (Python 实现)

目标:
    让真实 STM32 C 代码中的 HAL 函数调用，
    在 Python 仿真器中也能执行相同逻辑。

设计原则:
    1. 函数签名尽量匹配真实 HAL 库
    2. 内部路由到 VirtualDeviceBus
    3. 仅实现控制代码实际使用的 HAL 函数
    4. 不模拟完整 HAL 库

电机映射说明:
    真实小车 Motor1-4 与仿真器 motor[0-3] 的映射:
        Motor1 → motor[1] (BR, 后右)
        Motor2 → motor[0] (BL, 后左)
        Motor3 → motor[3] (FR, 前右)
        Motor4 → motor[2] (FL, 前左)

    此映射确保:
        Car_Forward  → 四轮同向, 前进
        Car_TurnLeft → 反时针旋转 (屏幕坐标)
        Car_TurnRight → 顺时针旋转
        Car_TransLeft → 左平移
        Car_TransRight → 右平移

使用方式:
    from stm32_compat.hal_stubs import hal
    hal.init()  # 绑定 VirtualDeviceBus
"""

# 全局设备总线引用 (由 init() 绑定)
_bus = None

# ── 电机映射表 ──
# MotorX → simulation motor[index]
MOTOR_MAP = {
    1: 1,  # Motor1 → motor[1] (BR)
    2: 0,  # Motor2 → motor[0] (BL)
    3: 3,  # Motor3 → motor[3] (FR)
    4: 2,  # Motor4 → motor[2] (FL)
}

# ── GPIO 端口/引脚常量 (与 STM32 标准库对齐) ──
GPIOA = 0x40020000
GPIOB = 0x40020400

GPIO_Pin_0  = 0x0001
GPIO_Pin_1  = 0x0002
GPIO_Pin_2  = 0x0004
GPIO_Pin_3  = 0x0008
GPIO_Pin_4  = 0x0010
GPIO_Pin_5  = 0x0020
GPIO_Pin_6  = 0x0040
GPIO_Pin_7  = 0x0080
GPIO_Pin_8  = 0x0100
GPIO_Pin_9  = 0x0200

# GPIO 模式常量
GPIO_Mode_IPU     = 0x48
GPIO_Mode_AF_PP   = 0x08
GPIO_Mode_Out_PP  = 0x02
GPIO_Speed_50MHz  = 0x02

# RCC 常量
RCC_APB1Periph_TIM2 = 0x00000001
RCC_APB1Periph_TIM4 = 0x00000004
RCC_APB2Periph_GPIOA = 0x00000004
RCC_APB2Periph_GPIOB = 0x00000008

# TIM 常量
TIM2 = 2
TIM4 = 4
TIM_CKD_DIV1           = 0x0000
TIM_CounterMode_Up     = 0x0000
TIM_OCMode_PWM1        = 0x0060
TIM_OCPolarity_High    = 0x0000
TIM_OutputState_Enable = 0x0001

# NVIC 常量
NVIC_PriorityGroup_2 = 0x0500


class GPIO_InitTypeDef:
    def __init__(self):
        self.GPIO_Pin = 0
        self.GPIO_Mode = 0
        self.GPIO_Speed = 0


class TIM_TimeBaseInitTypeDef:
    def __init__(self):
        self.TIM_ClockDivision = 0
        self.TIM_CounterMode = 0
        self.TIM_Period = 0
        self.TIM_Prescaler = 0
        self.TIM_RepetitionCounter = 0


class TIM_OCInitTypeDef:
    def __init__(self):
        self.TIM_OCMode = 0
        self.TIM_OCPolarity = 0
        self.TIM_OutputState = 0
        self.TIM_Pulse = 0


# ============================================================
#  传感器 HAL 函数
# ============================================================

def Sensor_Init():
    pass

def Sensor0_Get_State():
    return _bus.get_sensor_state('PB1')

def Sensor1_Get_State():
    return _bus.get_sensor_state('PB0')

def Sensor2_Get_State():
    return _bus.get_sensor_state('PB4')

def Sensor3_Get_State():
    return _bus.get_sensor_state('PB5')


# ============================================================
#  电机 HAL 函数 (含物理映射)
# ============================================================

def Motor_Init():
    pass

def Motor1_SetSpeed(Dir, Speed):
    Speed = min(999, max(0, Speed))
    _bus.set_motor(MOTOR_MAP[1], Dir, Speed)

def Motor2_SetSpeed(Dir, Speed):
    Speed = min(999, max(0, Speed))
    _bus.set_motor(MOTOR_MAP[2], Dir, Speed)

def Motor3_SetSpeed(Dir, Speed):
    Speed = min(999, max(0, Speed))
    _bus.set_motor(MOTOR_MAP[3], Dir, Speed)

def Motor4_SetSpeed(Dir, Speed):
    Speed = min(999, max(0, Speed))
    _bus.set_motor(MOTOR_MAP[4], Dir, Speed)


# ============================================================
#  底层 HAL 桩 (仿真中为 no-op)
# ============================================================

def GPIO_Init(port, init_struct):
    pass

def GPIO_ReadInputDataBit(port, pin):
    pin_map = {
        (GPIOB, GPIO_Pin_0): 'PB0',
        (GPIOB, GPIO_Pin_1): 'PB1',
        (GPIOB, GPIO_Pin_4): 'PB4',
        (GPIOB, GPIO_Pin_5): 'PB5',
    }
    key = (port, pin)
    if key in pin_map:
        return _bus.get_sensor_state(pin_map[key])
    return 0

def RCC_APB1PeriphClockCmd(periph, cmd):
    pass

def RCC_APB2PeriphClockCmd(periph, cmd):
    pass

def TIM_InternalClockConfig(timer):
    pass

def TIM_TimeBaseInit(timer, init_struct):
    pass

def TIM_OCStructInit(init_struct):
    pass

def TIM_OC1Init(timer, init_struct):
    pass

def TIM_OC2Init(timer, init_struct):
    pass

def TIM_OC3Init(timer, init_struct):
    pass

def TIM_OC4Init(timer, init_struct):
    pass

def TIM_Cmd(timer, cmd):
    pass

def TIM_SetCompare1(timer, value):
    pass

def TIM_SetCompare2(timer, value):
    pass

def TIM_SetCompare3(timer, value):
    pass

def TIM_SetCompare4(timer, value):
    pass

def NVIC_PriorityGroupConfig(group):
    pass


# ============================================================
#  小车高级控制函数 (与 Motor.c 一致)
# ============================================================

def Car_Stop():
    Motor1_SetSpeed(1, 0)
    Motor2_SetSpeed(1, 0)
    Motor3_SetSpeed(1, 0)
    Motor4_SetSpeed(1, 0)

def Car_Forward(Speed):
    Motor1_SetSpeed(0, Speed)
    Motor2_SetSpeed(0, Speed)
    Motor3_SetSpeed(0, Speed)
    Motor4_SetSpeed(0, Speed)

def Car_Backward(Speed):
    Motor1_SetSpeed(1, Speed)
    Motor2_SetSpeed(1, Speed)
    Motor3_SetSpeed(1, Speed)
    Motor4_SetSpeed(1, Speed)

def Car_TurnLeft(Speed):
    Motor1_SetSpeed(0, Speed)
    Motor2_SetSpeed(1, Speed)
    Motor3_SetSpeed(1, Speed)
    Motor4_SetSpeed(0, Speed)

def Car_TurnRight(Speed):
    Motor1_SetSpeed(1, Speed)
    Motor2_SetSpeed(0, Speed)
    Motor3_SetSpeed(0, Speed)
    Motor4_SetSpeed(1, Speed)

def Car_TransLeft(Speed):
    Motor1_SetSpeed(1, Speed)
    Motor2_SetSpeed(0, Speed)
    Motor3_SetSpeed(1, Speed)
    Motor4_SetSpeed(0, Speed)

def Car_TransRight(Speed):
    Motor1_SetSpeed(0, Speed)
    Motor2_SetSpeed(1, Speed)
    Motor3_SetSpeed(0, Speed)
    Motor4_SetSpeed(1, Speed)


# ============================================================
#  延时函数
# ============================================================

def Delay_ms(ms):
    _bus.delay_ms(ms)


# ============================================================
#  HAL 初始化
# ============================================================

def init(bus):
    global _bus
    _bus = bus

def get_bus():
    return _bus
