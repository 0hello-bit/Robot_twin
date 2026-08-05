# -*- coding: utf-8 -*-
"""
sensor_resolution_eval.py - 传感器分辨率评估模块

分析离散 vs 连续传感器对控制性能的影响。
"""

import json
import os
import time


class SensorResolutionEvaluator:
    """传感器分辨率评估器"""

    def evaluate(self, test_results, analysis):
        report = {
            'timestamp': time.time(),
            'sensor_discrete_vs_continuous': {},
            'controller_baseline_vs_adaptive': {},
            'bottleneck_analysis': {},
            'recommendations': [],
        }

        sc = analysis.get('sensor_comparison', [])
        cc = analysis.get('controller_comparison', [])

        # 1. Sensor comparison summary
        if sc:
            improvements = [c['error_improvement_pct'] for c in sc]
            avg_imp = sum(improvements) / len(improvements)
            report['sensor_discrete_vs_continuous'] = {
                'avg_error_improvement_pct': round(avg_imp, 2),
                'best_improvement_pct': round(max(improvements), 2),
                'worst_improvement_pct': round(min(improvements), 2),
                'scenarios_improved': sum(1 for x in improvements if x > 0),
                'total_scenarios': len(improvements),
                'osc_change_avg': round(
                    sum(c['continuous_osc'] - c['discrete_osc'] for c in sc) / len(sc), 4),
                'pwm_change_avg': round(
                    sum(c['continuous_pwm'] - c['discrete_pwm'] for c in sc) / len(sc), 2),
            }

        # 2. Controller comparison summary
        if cc:
            improvements = [c['improvement_pct'] for c in cc]
            report['controller_baseline_vs_adaptive'] = {
                'avg_improvement_pct': round(sum(improvements) / len(improvements), 2),
                'best_improvement_pct': round(max(improvements), 2),
                'scenarios_improved': sum(1 for x in improvements if x > 0),
                'total_scenarios': len(improvements),
            }

        # 3. Bottleneck analysis
        sensor_adv = report.get('sensor_discrete_vs_continuous', {})
        ctrl_adv = report.get('controller_baseline_vs_adaptive', {})

        bottleneck = 'observation_resolution'
        if sensor_adv.get('avg_error_improvement_pct', 0) < 2:
            if ctrl_adv.get('avg_improvement_pct', 0) < 2:
                bottleneck = 'control_algorithm'
            else:
                bottleneck = 'partially_observation'

        report['bottleneck_analysis'] = {
            'primary_bottleneck': bottleneck,
            'observation_improves': sensor_adv.get('avg_error_improvement_pct', 0) > 2,
            'adaptive_benefits': ctrl_adv.get('avg_improvement_pct', 0) > 2,
        }

        # 4. Recommendations
        recs = report['recommendations']
        if sensor_adv.get('avg_error_improvement_pct', 0) < 2:
            recs.append('Observation resolution is NOT the primary bottleneck')
            recs.append('Consider: sensor placement, track design, or control algorithm')
        else:
            recs.append('Observation resolution IS a bottleneck - continuous sensor helps')

        if ctrl_adv.get('avg_improvement_pct', 0) < 2:
            recs.append('Adaptive PID does not significantly benefit from continuous sensor')
            recs.append('Consider: more sophisticated adaptation or different control approach')
        else:
            recs.append('Adaptive PID benefits from continuous sensor - proceed with tuning')

        recs.append('Next step: tune analog sensor sigma for optimal performance')

        return report

    def print_report(self, report):
        print()
        print("=" * 60)
        print("  Sensor Resolution Evaluation")
        print("=" * 60)

        sv = report.get('sensor_discrete_vs_continuous', {})
        print()
        print("  Discrete vs Continuous:")
        print("    Avg error improvement: {:+.1f}%".format(
            sv.get('avg_error_improvement_pct', 0)))
        print("    Best: {:+.1f}% Worst: {:+.1f}%".format(
            sv.get('best_improvement_pct', 0), sv.get('worst_improvement_pct', 0)))
        print("    Improved in {}/{} scenarios".format(
            sv.get('scenarios_improved', 0), sv.get('total_scenarios', 0)))

        cv = report.get('controller_baseline_vs_adaptive', {})
        print()
        print("  Baseline vs Adaptive (continuous):")
        print("    Avg improvement: {:+.1f}%".format(
            cv.get('avg_improvement_pct', 0)))

        bn = report.get('bottleneck_analysis', {})
        print()
        print("  Bottleneck: {}".format(bn.get('primary_bottleneck', '?')))

        print()
        print("  Recommendations:")
        for r in report.get('recommendations', []):
            print("    - {}".format(r))
        print()
        print("=" * 60)

    def save(self, report, filepath):
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print("[Eval] Saved:", filepath)