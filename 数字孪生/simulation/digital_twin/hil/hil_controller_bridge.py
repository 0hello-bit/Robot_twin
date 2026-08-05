# -*- coding: utf-8 -*-
"""
hil_controller_bridge.py - HIL 控制桥接器

功能:
    1. 将 PID optimizer 推荐参数发送回 STM32
    2. 支持安全限幅保护
    3. 支持 manual approval / auto deploy 模式
    4. 支持断线保护
    5. 支持参数下发确认

安全机制:
    - PID 参数范围严格限制
    - 必须经过 approval 才能下发
    - 蓝牙断线时自动停止下发
    - 下发后记录日志

使用:
    bridge = HilControllerBridge(serial_bridge)
    bridge.set_safe_limits({'kp': (1, 100), 'ki': (0, 10), 'kd': (0, 50)})
    result = bridge.deploy_pid(kp=40, ki=0.5, kd=15, auto=False)
"""

import time
import struct
import threading
import json
import os


class DeployMode:
    """部署模式"""
    SAFE = 'safe'           # 安全模式: 需要手动确认
    AUTO = 'auto'           # 自动模式: 直接下发
    MONITOR = 'monitor'     # 监控模式: 只读不写


# 默认安全限幅
DEFAULT_SAFE_LIMITS = {
    'kp': (1.0, 100.0),
    'ki': (0.0, 10.0),
    'kd': (0.0, 50.0),
    'base_speed': (100, 255),
}


class HilControllerBridge:
    """
    HIL 控制桥接器。

    将 Python 端的 PID 优化结果安全地发送回 STM32。

    使用:
        bridge = HilControllerBridge(serial_bridge)
        ok = bridge.deploy_pid(kp=40, ki=0.5, kd=15)
    """

    # 下发协议: ASCII CSV
    # 格式: P,kp,ki,kd,base_speed\n
    CMD_PREFIX_PID = 'P'
    CMD_PREFIX_MODE = 'M'
    CMD_PREFIX_SPEED = 'S'

    # 下发间隔限制 (秒)
    MIN_DEPLOY_INTERVAL = 2.0

    def __init__(self, serial_bridge=None, storage_dir=None):
        self._serial = serial_bridge
        self._lock = threading.Lock()

        # 安全限幅
        self._safe_limits = dict(DEFAULT_SAFE_LIMITS)

        # 部署模式
        self._mode = DeployMode.SAFE

        # 待确认队列
        self._pending_deploy = None

        # 部署历史
        self._deploy_history = []
        self._last_deploy_time = 0.0

        # 存储
        self._storage_dir = storage_dir
        if storage_dir:
            os.makedirs(storage_dir, exist_ok=True)

    def set_safe_limits(self, limits):
        """
        设置安全限幅。

        参数:
            limits: dict, 如 {'kp': (1, 100), 'ki': (0, 10)}
        """
        with self._lock:
            self._safe_limits.update(limits)

    def set_mode(self, mode):
        """设置部署模式"""
        self._mode = mode

    def validate_params(self, kp, ki, kd, base_speed=180):
        """
        验证参数是否在安全范围内。

        返回:
            dict: {'valid': bool, 'errors': list, 'warnings': list}
        """
        errors = []
        warnings = []

        with self._lock:
            limits = self._safe_limits

        # Kp
        kp_range = limits.get('kp', (1, 100))
        if kp < kp_range[0] or kp > kp_range[1]:
            errors.append('kp={:.2f} out of range [{}, {}]'.format(kp, kp_range[0], kp_range[1]))
        elif kp > kp_range[1] * 0.9:
            warnings.append('kp={:.2f} near upper limit'.format(kp))

        # Ki
        ki_range = limits.get('ki', (0, 10))
        if ki < ki_range[0] or ki > ki_range[1]:
            errors.append('ki={:.2f} out of range [{}, {}]'.format(ki, ki_range[0], ki_range[1]))

        # Kd
        kd_range = limits.get('kd', (0, 50))
        if kd < kd_range[0] or kd > kd_range[1]:
            errors.append('kd={:.2f} out of range [{}, {}]'.format(kd, kd_range[0], kd_range[1]))

        # Base speed
        spd_range = limits.get('base_speed', (100, 255))
        if base_speed < spd_range[0] or base_speed > spd_range[1]:
            errors.append('base_speed={} out of range [{}, {}]'.format(
                base_speed, spd_range[0], spd_range[1]))

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
        }

    def deploy_pid(self, kp, ki, kd, base_speed=180, auto=False):
        """
        下发 PID 参数到 STM32。

        参数:
            kp, ki, kd:     PID 参数
            base_speed:     基础速度 PWM
            auto:           是否跳过确认

        返回:
            dict: {'success': bool, 'message': str, 'validation': dict}
        """
        # 验证参数
        validation = self.validate_params(kp, ki, kd, base_speed)

        if not validation['valid']:
            return {
                'success': False,
                'message': 'Validation failed',
                'validation': validation,
            }

        # 检查连接
        if self._serial and not self._serial.is_connected():
            return {
                'success': False,
                'message': 'Serial not connected',
                'validation': validation,
            }

        # 检查部署间隔
        now = time.monotonic()
        if (now - self._last_deploy_time) < self.MIN_DEPLOY_INTERVAL:
            return {
                'success': False,
                'message': 'Deploy too frequent (min {}s)'.format(self.MIN_DEPLOY_INTERVAL),
                'validation': validation,
            }

        # 安全模式: 需要确认
        if self._mode == DeployMode.SAFE and not auto:
            with self._lock:
                self._pending_deploy = {
                    'kp': kp, 'ki': ki, 'kd': kd,
                    'base_speed': base_speed,
                    'timestamp': now,
                    'validation': validation,
                }
            return {
                'success': False,
                'message': 'Pending approval. Call confirm_deploy() to send.',
                'validation': validation,
                'pending': True,
            }

        # 监控模式: 不允许下发
        if self._mode == DeployMode.MONITOR:
            return {
                'success': False,
                'message': 'Monitor mode - no deployment allowed',
                'validation': validation,
            }

        # 执行下发
        return self._send_pid(kp, ki, kd, base_speed, validation)

    def confirm_deploy(self):
        """
        确认待下发的参数。

        返回:
            dict: 下发结果
        """
        with self._lock:
            pending = self._pending_deploy
            self._pending_deploy = None

        if pending is None:
            return {
                'success': False,
                'message': 'No pending deployment',
            }

        return self._send_pid(
            pending['kp'], pending['ki'], pending['kd'],
            pending['base_speed'], pending['validation']
        )

    def cancel_deploy(self):
        """取消待下发的参数"""
        with self._lock:
            self._pending_deploy = None
        return True

    def get_pending(self):
        """获取待确认的部署"""
        with self._lock:
            return self._pending_deploy

    def _send_pid(self, kp, ki, kd, base_speed, validation):
        """实际发送 PID 参数"""
        # 构建 ASCII 命令
        cmd = '{},{:.2f},{:.2f},{:.2f},{}\n'.format(
            self.CMD_PREFIX_PID, kp, ki, kd, int(base_speed))

        # 发送
        sent = False
        if self._serial and self._serial.is_connected():
            try:
                sent = self._serial.send_command(cmd.strip())
            except Exception:
                sent = False

        # 记录
        record = {
            'timestamp': time.time(),
            'kp': kp, 'ki': ki, 'kd': kd,
            'base_speed': base_speed,
            'sent': sent,
            'validation': validation,
        }

        with self._lock:
            self._deploy_history.append(record)
            self._last_deploy_time = time.monotonic()

        # 保存到文件
        if self._storage_dir:
            self._save_deploy_log(record)

        return {
            'success': sent,
            'message': 'Deployed' if sent else 'Send failed (no connection)',
            'validation': validation,
            'command': cmd.strip(),
        }

    def _save_deploy_log(self, record):
        """保存部署日志"""
        try:
            path = os.path.join(self._storage_dir, 'deploy_log.json')
            history = []
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            history.append(record)
            # 保留最近 100 条
            if len(history) > 100:
                history = history[-100:]
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_deploy_history(self, last_n=None):
        """获取部署历史"""
        with self._lock:
            if last_n:
                return self._deploy_history[-last_n:]
            return list(self._deploy_history)

    def get_stats(self):
        """获取部署统计"""
        with self._lock:
            total = len(self._deploy_history)
            success = sum(1 for r in self._deploy_history if r.get('sent'))
            return {
                'total_deploys': total,
                'successful_deploys': success,
                'success_rate_pct': round(success / max(total, 1) * 100, 1),
                'mode': self._mode,
                'pending': self._pending_deploy is not None,
            }

    def reset(self):
        """重置桥接器"""
        with self._lock:
            self._pending_deploy = None
            self._deploy_history.clear()
            self._last_deploy_time = 0.0