# -*- coding: utf-8 -*-
"""
system_health_dashboard.py - 系统健康度仪表板

功能:
    统一输出:
        - 模型置信度趋势
        - 校准改善曲线
        - PID 成功率
        - sim-real 误差趋势
        - 整体健康评分
"""

import json
import os
import time


class SystemHealthDashboard:
    """
    系统健康度仪表板。

    使用方式:
        dash = SystemHealthDashboard()
        dash.update(trend_record, confidence, validation_result)
        report = dash.get_report()
        dash.print_report()
    """

    def __init__(self):
        self.snapshots = []

    def update(self, trend_record=None, confidence=None,
               validation_result=None, ab_result=None, ground_truth=None):
        """添加一个快照"""
        snapshot = {
            'timestamp': time.time(),
            'trend': trend_record,
            'confidence': confidence,
            'validation': validation_result,
            'ab_test': ab_result,
            'ground_truth': ground_truth,
        }
        self.snapshots.append(snapshot)

    def get_report(self):
        """生成综合报告"""
        if not self.snapshots:
            return {'status': 'no_data'}

        latest = self.snapshots[-1]

        # 计算整体健康评分
        health_score = 50.0
        health_details = {}

        # 置信度贡献 (30%)
        conf = latest.get('confidence')
        if conf and isinstance(conf, dict):
            cs = conf.get('confidence_score', 50)
            health_score += (cs - 50) * 0.3
            health_details['confidence'] = cs

        # 验证准确度贡献 (30%)
        val = latest.get('validation')
        if val and isinstance(val, dict):
            vs = val.get('accuracy_score', 50)
            health_score += (vs - 50) * 0.3
            health_details['validation_accuracy'] = vs

        # 趋势贡献 (20%)
        trend = latest.get('trend')
        if trend and isinstance(trend, dict):
            t = trend.get('error_trend', 'stable')
            trend_bonus = {'improving': 10, 'stable': 0, 'oscillating': -5, 'diverging': -15}
            health_score += trend_bonus.get(t, 0)
            health_details['error_trend'] = t

        # A/B 测试贡献 (20%)
        ab = latest.get('ab_test')
        if ab and isinstance(ab, dict):
            if ab.get('winner') == 'B':
                health_score += 10
            elif ab.get('winner') == 'tie':
                health_score += 5
            health_details['ab_winner'] = ab.get('winner', 'unknown')

        health_score = max(0, min(100, health_score))

        # 健康等级
        if health_score >= 80:
            health_grade = 'EXCELLENT'
        elif health_score >= 65:
            health_grade = 'GOOD'
        elif health_score >= 50:
            health_grade = 'FAIR'
        elif health_score >= 35:
            health_grade = 'POOR'
        else:
            health_grade = 'CRITICAL'

        return {
            'health_score': round(health_score, 1),
            'health_grade': health_grade,
            'health_details': health_details,
            'n_snapshots': len(self.snapshots),
            'latest_timestamp': latest['timestamp'],
        }

    def get_history(self):
        """获取历史快照"""
        return list(self.snapshots)

    def save_report(self, filepath):
        """保存报告"""
        report = {
            'report': self.get_report(),
            'history': self.snapshots[-10:],  # 最近 10 条
            'total_snapshots': len(self.snapshots),
            'timestamp': time.time(),
        }
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print("[Dashboard] Report saved: {}".format(filepath))

    def print_report(self):
        """打印报告"""
        r = self.get_report()
        print("\n" + "=" * 55)
        print("  System Health Dashboard")
        print("=" * 55)
        print("  Health Score:  {:.1f} / 100".format(r['health_score']))
        print("  Health Grade:  {}".format(r['health_grade']))
        print("  Snapshots:     {}".format(r['n_snapshots']))
        for k, v in r['health_details'].items():
            print("  {}: {}".format(k, v))
        print("=" * 55)