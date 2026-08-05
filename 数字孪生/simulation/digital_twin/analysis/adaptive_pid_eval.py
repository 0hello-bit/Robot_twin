# -*- coding: utf-8 -*-
"""
adaptive_pid_eval.py - Adaptive PID 评估分析模块

职责:
    1. 解析 A/B/C 实验结果
    2. 输出结构化评估报告
    3. 生成 JSON 输出 (含 confidence_score)
    4. 识别过调 / 抖动 / 场景弱点

使用方式:
    from analysis.adaptive_pid_eval import AdaptivePIDEvaluator
    evaluator = AdaptivePIDEvaluator()
    report = evaluator.evaluate(results)
    evaluator.print_report(report)
"""

import math
import json
import os
import time


class AdaptivePIDEvaluator:
    """
    Adaptive PID 评估分析器。

    接收 PIDABTest 的结果, 输出结构化评估报告。

    使用:
        evaluator = AdaptivePIDEvaluator()
        report = evaluator.evaluate(ab_test_results)
        evaluator.print_report(report)
        evaluator.save_report(report, 'report.json')
    """

    # 评估权重
    WEIGHTS = {
        'tracking_error': 0.25,
        'stability': 0.20,
        'convergence': 0.15,
        'robustness': 0.20,
        'control_effort': 0.10,
        'lost_line': 0.10,
    }

    def evaluate(self, ab_results):
        """
        评估 A/B/C 实验结果。

        参数:
            ab_results: PIDABTest.run_all() 的输出

        返回:
            dict: 结构化评估报告
        """
        summary = ab_results.get('summary', {})
        conclusion = ab_results.get('conclusion', {})

        # 提取 clean 和 noisy 场景数据
        a_clean = summary.get('A_baseline', {}).get('clean', {})
        b_clean = summary.get('B_adaptive', {}).get('clean', {})
        c_clean = summary.get('C_control', {}).get('clean', {})
        a_noisy = summary.get('A_baseline', {}).get('noisy', {})
        b_noisy = summary.get('B_adaptive', {}).get('noisy', {})

        # ── 1. Tracking Error 评估 ──
        tracking = self._eval_tracking(a_clean, b_clean, c_clean)

        # ── 2. Stability 评估 ──
        stability = self._eval_stability(a_clean, b_clean, c_clean)

        # ── 3. Convergence 评估 ──
        convergence = self._eval_convergence(a_clean, b_clean, c_clean)

        # ── 4. Robustness 评估 ──
        robustness = self._eval_robustness(
            a_clean, b_clean, a_noisy, b_noisy)

        # ── 5. Control Effort 评估 ──
        effort = self._eval_effort(a_clean, b_clean, c_clean)

        # ── 6. Lost Line 评估 ──
        lost = self._eval_lost_line(a_clean, b_clean, a_noisy, b_noisy)

        # ── 综合评分 ──
        dimensions = {
            'tracking_error': tracking,
            'stability': stability,
            'convergence': convergence,
            'robustness': robustness,
            'control_effort': effort,
            'lost_line': lost,
        }

        # 加权综合得分
        b_score = sum(
            dimensions[k]['b_score'] * self.WEIGHTS[k]
            for k in self.WEIGHTS
        )

        # 场景弱点分析
        weaknesses = self._find_weaknesses(summary)

        # 过调检测
        overcontrol = self._detect_overcontrol(a_clean, b_clean)

        # 最终报告
        report = {
            'experiment': {
                'params': ab_results.get('params', {}),
                'config': ab_results.get('config', {}),
                'timestamp': ab_results.get('timestamp', 0),
            },
            'dimensions': dimensions,
            'overall': {
                'adaptive_score': round(b_score, 2),
                'winner': conclusion.get('winner', '?'),
                'verdict': conclusion.get('verdict', ''),
                'confidence': conclusion.get('confidence', 0),
                'reasons': conclusion.get('reasons', []),
                'warnings': conclusion.get('warnings', []),
            },
            'weaknesses': weaknesses,
            'overcontrol_analysis': overcontrol,
            'raw_summary': summary,
        }

        return report

    def _eval_tracking(self, a, b, c):
        """评估跟踪误差"""
        a_err = a.get('mean_error', 999)
        b_err = b.get('mean_error', 999)
        c_err = c.get('mean_error', 999)

        # B 相对 A 的改善率
        if a_err > 1e-10:
            improvement = (a_err - b_err) / a_err * 100
        else:
            improvement = 0

        # B 相对 C 的比较 (C 是随机扰动基线)
        if c_err > 1e-10:
            vs_control = (c_err - b_err) / c_err * 100
        else:
            vs_control = 0

        # 评分: 改善 > 10% = 满分, 0% = 一半, 负值 = 低分
        b_score = max(0, min(100, 50 + improvement * 2))

        return {
            'a_mean_error': a_err,
            'b_mean_error': b_err,
            'c_mean_error': c_err,
            'b_vs_a_improvement_pct': round(improvement, 2),
            'b_vs_c_improvement_pct': round(vs_control, 2),
            'b_score': round(b_score, 1),
            'a_max_error': a.get('max_error', 0),
            'b_max_error': b.get('max_error', 0),
        }

    def _eval_stability(self, a, b, c):
        """评估稳定性"""
        a_var = a.get('error_variance', 999)
        b_var = b.get('error_variance', 999)
        c_var = c.get('error_variance', 999)

        a_osc = a.get('osc_freq', 0)
        b_osc = b.get('osc_freq', 0)

        # 方差改善
        if a_var > 1e-10:
            var_improvement = (a_var - b_var) / a_var * 100
        else:
            var_improvement = 0

        # 震荡变化
        if a_osc > 1e-10:
            osc_change = (b_osc - a_osc) / a_osc * 100
        else:
            osc_change = 0

        # 评分: 方差降低 = 好, 震荡增加 = 差
        b_score = 50
        b_score += min(25, var_improvement * 0.5)
        b_score -= min(25, max(0, osc_change) * 0.3)
        b_score = max(0, min(100, b_score))

        return {
            'a_error_variance': a_var,
            'b_error_variance': b_var,
            'c_error_variance': c_var,
            'variance_improvement_pct': round(var_improvement, 2),
            'a_osc_freq': a_osc,
            'b_osc_freq': b_osc,
            'osc_change_pct': round(osc_change, 2),
            'b_score': round(b_score, 1),
        }

    def _eval_convergence(self, a, b, c):
        """评估收敛速度"""
        a_settle = a.get('settle_time_s', 999)
        b_settle = b.get('settle_time_s', 999)
        c_settle = c.get('settle_time_s', 999)

        if a_settle > 1e-10:
            speedup = (a_settle - b_settle) / a_settle * 100
        else:
            speedup = 0

        b_score = max(0, min(100, 50 + speedup * 1.5))

        return {
            'a_settle_time_s': a_settle,
            'b_settle_time_s': b_settle,
            'c_settle_time_s': c_settle,
            'speedup_pct': round(speedup, 2),
            'b_score': round(b_score, 1),
        }

    def _eval_robustness(self, a_clean, b_clean, a_noisy, b_noisy):
        """评估抗噪能力"""
        a_clean_err = a_clean.get('mean_error', 999)
        b_clean_err = b_clean.get('mean_error', 999)
        a_noisy_err = a_noisy.get('mean_error', 999)
        b_noisy_err = b_noisy.get('mean_error', 999)

        # 噪声下性能下降比例
        if a_clean_err > 1e-10:
            a_degradation = (a_noisy_err - a_clean_err) / a_clean_err * 100
        else:
            a_degradation = 0

        if b_clean_err > 1e-10:
            b_degradation = (b_noisy_err - b_clean_err) / b_clean_err * 100
        else:
            b_degradation = 0

        # B 比 A 更抗噪 = B 的 degradation 更小
        robustness_advantage = a_degradation - b_degradation

        b_score = max(0, min(100, 50 + robustness_advantage * 2))

        return {
            'a_noise_degradation_pct': round(a_degradation, 2),
            'b_noise_degradation_pct': round(b_degradation, 2),
            'robustness_advantage_pct': round(robustness_advantage, 2),
            'a_noisy_error': a_noisy_err,
            'b_noisy_error': b_noisy_err,
            'b_score': round(b_score, 1),
        }

    def _eval_effort(self, a, b, c):
        """评估控制量"""
        a_pwm = a.get('mean_pwm_change', 999)
        b_pwm = b.get('mean_pwm_change', 999)
        c_pwm = c.get('mean_pwm_change', 999)

        # PWM 变化越小越好 (平滑控制)
        if a_pwm > 1e-10:
            change = (a_pwm - b_pwm) / a_pwm * 100
        else:
            change = 0

        b_score = max(0, min(100, 50 + change * 1.0))

        return {
            'a_mean_pwm_change': a_pwm,
            'b_mean_pwm_change': b_pwm,
            'c_mean_pwm_change': c_pwm,
            'change_pct': round(change, 2),
            'b_score': round(b_score, 1),
        }

    def _eval_lost_line(self, a_clean, b_clean, a_noisy, b_noisy):
        """评估丢线率"""
        a_lost = a_clean.get('lost_pct', 0)
        b_lost = b_clean.get('lost_pct', 0)
        a_lost_n = a_noisy.get('lost_pct', 0)
        b_lost_n = b_noisy.get('lost_pct', 0)

        # 丢线率越低越好
        lost_improvement = a_lost - b_lost
        noisy_improvement = a_lost_n - b_lost_n

        b_score = 50 + lost_improvement * 2 + noisy_improvement * 1
        b_score = max(0, min(100, b_score))

        return {
            'a_lost_pct_clean': a_lost,
            'b_lost_pct_clean': b_lost,
            'a_lost_pct_noisy': a_lost_n,
            'b_lost_pct_noisy': b_lost_n,
            'b_score': round(b_score, 1),
        }

    def _find_weaknesses(self, summary):
        """识别 Adaptive PID 在哪些场景表现变差"""
        weaknesses = []

        for cond_label in ['clean', 'noisy']:
            a = summary.get('A_baseline', {}).get(cond_label, {})
            b = summary.get('B_adaptive', {}).get(cond_label, {})

            if not a or not b:
                continue

            prefix = '[{}] '.format(cond_label)

            # 检查: B 的误差比 A 大
            if b.get('mean_error', 0) > a.get('mean_error', 0) * 1.05:
                weaknesses.append({
                    'type': 'higher_error',
                    'scene': cond_label,
                    'detail': '{}B mean error ({:.3f}) > A ({:.3f})'.format(
                        prefix, b['mean_error'], a['mean_error']),
                })

            # 检查: B 的震荡比 A 多
            if b.get('osc_freq', 0) > a.get('osc_freq', 0) * 1.2:
                weaknesses.append({
                    'type': 'more_oscillation',
                    'scene': cond_label,
                    'detail': '{}B osc freq ({:.3f}) > A ({:.3f})'.format(
                        prefix, b['osc_freq'], a['osc_freq']),
                })

            # 检查: B 的控制量比 A 大很多
            if b.get('mean_pwm_change', 0) > a.get('mean_pwm_change', 0) * 1.3:
                weaknesses.append({
                    'type': 'more_control_effort',
                    'scene': cond_label,
                    'detail': '{}B PWM change ({:.1f}) >> A ({:.1f})'.format(
                        prefix, b['mean_pwm_change'], a['mean_pwm_change']),
                })

            # 检查: B 收敛更慢
            if b.get('settle_time_s', 0) > a.get('settle_time_s', 0) * 1.2:
                weaknesses.append({
                    'type': 'slower_convergence',
                    'scene': cond_label,
                    'detail': '{}B settle ({:.2f}s) > A ({:.2f}s)'.format(
                        prefix, b['settle_time_s'], a['settle_time_s']),
                })

        return weaknesses

    def _detect_overcontrol(self, a_clean, b_clean):
        """检测是否存在过调"""
        analysis = {
            'detected': False,
            'signals': [],
        }

        # 信号 1: 控制量变化显著增大
        a_pwm = a_clean.get('mean_pwm_change', 0)
        b_pwm = b_clean.get('mean_pwm_change', 0)
        if a_pwm > 1e-10 and b_pwm > a_pwm * 1.3:
            analysis['detected'] = True
            analysis['signals'].append({
                'type': 'excessive_pwm_change',
                'detail': 'B PWM change {:.1f} > A {:.1f} (+{:.0f}%)'.format(
                    b_pwm, a_pwm, (b_pwm / a_pwm - 1) * 100),
            })

        # 信号 2: 震荡频率显著增加
        a_osc = a_clean.get('osc_freq', 0)
        b_osc = b_clean.get('osc_freq', 0)
        if a_osc > 1e-10 and b_osc > a_osc * 1.5:
            analysis['detected'] = True
            analysis['signals'].append({
                'type': 'excessive_oscillation',
                'detail': 'B osc freq {:.3f} > A {:.3f} (+{:.0f}%)'.format(
                    b_osc, a_osc, (b_osc / a_osc - 1) * 100),
            })

        # 信号 3: 误差方差增大
        a_var = a_clean.get('error_variance', 0)
        b_var = b_clean.get('error_variance', 0)
        if a_var > 1e-10 and b_var > a_var * 1.5:
            analysis['detected'] = True
            analysis['signals'].append({
                'type': 'increased_variance',
                'detail': 'B error variance {:.4f} > A {:.4f}'.format(
                    b_var, a_var),
            })

        if not analysis['signals']:
            analysis['detail'] = 'No over-control signals detected'

        return analysis

    def print_report(self, report):
        """打印评估报告"""
        print()
        print("=" * 60)
        print("  Adaptive PID Evaluation Report")
        print("=" * 60)

        exp = report.get('experiment', {})
        print("  Params: Kp={} Ki={} Kd={}".format(
            exp.get('params', {}).get('kp'),
            exp.get('params', {}).get('ki'),
            exp.get('params', {}).get('kd')))

        dims = report.get('dimensions', {})
        for dim_name, dim_data in dims.items():
            score = dim_data.get('b_score', 0)
            print()
            print("  [{}] Score: {:.1f}/100".format(dim_name, score))
            for k, v in dim_data.items():
                if k != 'b_score':
                    print("    {}: {}".format(k, v))

        overall = report.get('overall', {})
        print()
        print("  --- Overall ---")
        print("  Adaptive Score: {:.1f}/100".format(
            overall.get('adaptive_score', 0)))
        print("  Winner: Group {}".format(overall.get('winner', '?')))
        print("  Verdict: {}".format(overall.get('verdict', '')))
        print("  Confidence: {}/100".format(overall.get('confidence', 0)))

        if overall.get('reasons'):
            print("  Reasons:")
            for r in overall['reasons']:
                print("    + {}".format(r))
        if overall.get('warnings'):
            print("  Warnings:")
            for w in overall['warnings']:
                print("    ! {}".format(w))

        weaknesses = report.get('weaknesses', [])
        if weaknesses:
            print()
            print("  --- Weaknesses ---")
            for w in weaknesses:
                print("    [{}] {}".format(w['type'], w['detail']))

        oc = report.get('overcontrol_analysis', {})
        print()
        print("  --- Over-control ---")
        if oc.get('detected'):
            print("  DETECTED:")
            for s in oc.get('signals', []):
                print("    ! {}".format(s['detail']))
        else:
            print("  Not detected")

        print()
        print("=" * 60)

    def save_report(self, report, filepath):
        """保存报告为 JSON"""
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print("[Eval] Saved: {}".format(filepath))

    def get_json_output(self, report):
        """获取符合要求格式的 JSON 输出"""
        overall = report.get('overall', {})
        dims = report.get('dimensions', {})

        return {
            'A_baseline': {
                'tracking_error': dims.get('tracking_error', {}).get('a_mean_error', 0),
                'stability': dims.get('stability', {}).get('a_error_variance', 0),
                'convergence': dims.get('convergence', {}).get('a_settle_time_s', 0),
                'control_effort': dims.get('control_effort', {}).get('a_mean_pwm_change', 0),
            },
            'B_adaptive': {
                'tracking_error': dims.get('tracking_error', {}).get('b_mean_error', 0),
                'stability': dims.get('stability', {}).get('b_error_variance', 0),
                'convergence': dims.get('convergence', {}).get('b_settle_time_s', 0),
                'control_effort': dims.get('control_effort', {}).get('b_mean_pwm_change', 0),
                'score': overall.get('adaptive_score', 0),
            },
            'C_control': {
                'tracking_error': dims.get('tracking_error', {}).get('c_mean_error', 0),
                'stability': dims.get('stability', {}).get('c_error_variance', 0),
                'convergence': dims.get('convergence', {}).get('c_settle_time_s', 0),
                'control_effort': dims.get('control_effort', {}).get('c_mean_pwm_change', 0),
            },
            'conclusion': overall.get('verdict', ''),
            'confidence_score': overall.get('confidence', 0),
            'weaknesses': report.get('weaknesses', []),
            'overcontrol': report.get('overcontrol_analysis', {}).get('detected', False),
        }