# -*- coding: utf-8 -*-
"""
pid_ab_test.py - Adaptive PID A/B/C 对照实验
"""

import math
import random
import json
import os
import time

from simulator.pid import PIDController
from simulator.map import TrackMap
from control_sandbox.plant_model import PlantModel
from control.adaptive_pid import AdaptivePID
from analysis.control_fitness import ControlFitness


class PIDLineFollower:
    WEIGHTS = [-3.0, -1.0, 1.0, 3.0]
    def __init__(self, kp=0.6, ki=0.0, kd=0.15, base_speed=180):
        self.pid = PIDController(kp=kp, ki=ki, kd=kd)
        self.base_speed = base_speed
        self.lost_counter = 0
        self.last_position = 0
    def reset(self):
        self.pid.reset(); self.lost_counter = 0; self.last_position = 0
    def step(self, s0, s1, s2, s3, dt=0.03):
        position = 0; black_count = 0
        if s0 == 0: position += -3; black_count += 1
        if s1 == 0: position += -1; black_count += 1
        if s2 == 0: position += +1; black_count += 1
        if s3 == 0: position += +3; black_count += 1
        if black_count == 4:
            self.lost_counter += 1
            if self.lost_counter == 1:
                self.last_position = 1 if self.last_position > 0 else -1
            if self.lost_counter > 40:
                self.last_position = -self.last_position; self.lost_counter = 0
            return (500, -500) if self.last_position > 0 else (-500, 500)
        elif black_count == 0:
            self.lost_counter = 0; return (120, 120)
        else:
            self.lost_counter = 0
            if position != 0: self.last_position = position
            pid_out = max(-1.0, min(1.0, self.pid.compute(position, dt)))
            base = self.base_speed / 999.0
            left = max(-1.0, min(1.0, base + pid_out * 0.5))
            right = max(-1.0, min(1.0, base - pid_out * 0.5))
            return (left * 999, right * 999)
    def get_pid(self):
        return self.pid


def make_a(kp, ki, kd):
    return PIDLineFollower(kp=kp, ki=ki, kd=kd), None

def make_b(kp, ki, kd):
    c = PIDLineFollower(kp=kp, ki=ki, kd=kd)
    return c, AdaptivePID(kp=kp, ki=ki, kd=kd)

def make_c(kp, ki, kd, seed=42):
    rng = random.Random(seed)
    return PIDLineFollower(
        kp=kp*(1+rng.uniform(-0.05,0.05)),
        ki=ki*(1+rng.uniform(-0.05,0.05)),
        kd=kd*(1+rng.uniform(-0.05,0.05))), None


def run_one(ctrl, apid, max_ticks, dt, noise, plant):
    plant.reset(x=400, y=450, angle=0)
    plant.noise_enabled = noise
    traj, s_hist, m_hist, errs = [], [], [], []
    for tick in range(max_ticks):
        s = plant.read_sensors()
        s0, s1, s2, s3 = s
        if apid is not None:
            pos = 0
            if s0==0: pos+=-3
            if s1==0: pos+=-1
            if s2==0: pos+=1
            if s3==0: pos+=3
            deriv = (pos - errs[-1]) / dt if tick > 0 else 0.0
            kp, ki, kd = apid.update(pos, deriv, dt)
            ctrl.get_pid().set_gains(kp, ki, kd)
        lp, rp = ctrl.step(s0, s1, s2, s3, dt)
        ns = plant.step(lp, rp, dt)
        pos = 0
        if ns[0]==0: pos+=-3
        if ns[1]==0: pos+=-1
        if ns[2]==0: pos+=1
        if ns[3]==0: pos+=3
        errs.append(pos)
        st = plant.get_state_dict()
        st['t']=tick*dt; st['tick']=tick; st['sensors']=ns
        st['left_pwm']=lp; st['right_pwm']=rp
        st['position_error']=pos
        st['black_count']=sum(1 for x in ns if x==0)
        traj.append(st); s_hist.append(ns); m_hist.append((lp,rp))
    return {'trajectory':traj,'sensor_history':s_hist,'motor_history':m_hist,
            'errors':errs,'max_ticks':max_ticks,'dt':dt,'noise':noise}


class PIDABTest:
    def __init__(self, kp=0.6, ki=0.0, kd=0.15):
        self.kp=kp; self.ki=ki; self.kd=kd
        self.fitness = ControlFitness()

    def run_all(self, seeds=5, max_ticks=2000, dt=0.03, noise_list=None, model_dir=None):
        if noise_list is None:
            noise_list = [(False,'clean'),(True,'noisy')]
        plant = PlantModel(model_dir)
        track = TrackMap()
        pts = track.generate_oval(400, 300, 200, 150, num_points=200)
        track.add_polyline(pts)
        plant.set_track(track)

        groups = {'A_baseline':('A: Baseline PID','a'),
                  'B_adaptive':('B: Adaptive PID','b'),
                  'C_control':('C: Perturbed PID','c')}
        results = {}
        for gk,(label,gt) in groups.items():
            gres = []
            for noise_on,nl in noise_list:
                nres = []
                for si in range(seeds):
                    seed = si*1000+(0 if not noise_on else 7)
                    if gt=='a': ctrl,apid = make_a(self.kp,self.ki,self.kd)
                    elif gt=='b': ctrl,apid = make_b(self.kp,self.ki,self.kd)
                    else: ctrl,apid = make_c(self.kp,self.ki,self.kd,seed)
                    ctrl.reset()
                    exp = run_one(ctrl,apid,max_ticks,dt,noise_on,plant)
                    fit = self.fitness.evaluate(exp['trajectory'],exp['sensor_history'],exp['motor_history'])
                    ext = self._metrics(exp)
                    nres.append({'seed':seed,'fitness':fit,'extra':ext,'errors':exp['errors']})
                gres.append({'noise':noise_on,'noise_label':nl,'runs':nres})
            results[gk] = {'label':label,'conditions':gres}

        summary = self._summarize(results)
        results['summary'] = summary
        results['conclusion'] = self._conclude(summary)
        results['params'] = {'kp':self.kp,'ki':self.ki,'kd':self.kd}
        results['config'] = {'seeds':seeds,'max_ticks':max_ticks,'dt':dt}
        results['timestamp'] = time.time()
        return results

    def _metrics(self, exp):
        e=exp['errors']; m=exp['motor_history']; n=len(e)
        if n==0: return {}
        ae=[abs(x) for x in e]
        me=sum(ae)/n; mx=max(ae)
        zc=sum(1 for i in range(1,n) if e[i-1]*e[i]<0)
        of=zc/max(n,1)*2
        em=sum(e)/n; ev=sum((x-em)**2 for x in e)/n
        th=0.5; st=n; sw=max(n//5,10)
        for i in range(n-sw,-1,-1):
            w=e[i:i+sw]
            if all(abs(x)<=th for x in w): st=i
            else: break
        st_t=st*exp['dt']
        pc=[]
        for i in range(1,n):
            pc.append((abs(m[i][0]-m[i-1][0])+abs(m[i][1]-m[i-1][1]))/2.0)
        mpc=sum(pc)/max(len(pc),1); xpc=max(pc) if pc else 0
        lc=sum(1 for s in exp['sensor_history'] if all(v==1 for v in s))
        lp=lc/n*100
        return {'mean_error':round(me,4),'max_error':round(mx,4),
                'osc_count':zc,'osc_freq':round(of,4),
                'error_variance':round(ev,4),
                'settle_time_s':round(st_t,3),'settle_tick':st,
                'mean_pwm_change':round(mpc,2),'max_pwm_change':round(xpc,2),
                'lost_pct':round(lp,2)}

    def _summarize(self, results):
        s={}
        for gk in ['A_baseline','B_adaptive','C_control']:
            gs={}
            for c in results[gk]['conditions']:
                lb=c['noise_label']; runs=c['runs']
                ml=[r['extra'] for r in runs if r['extra']]
                fl=[r['fitness']['score'] for r in runs]
                if not ml: gs[lb]={}; continue
                av={}
                for k in ml[0]:
                    vs=[x[k] for x in ml]
                    av[k]=round(sum(vs)/len(vs),4)
                av['fitness_score']=round(sum(fl)/len(fl),2) if fl else 0
                for k in ['mean_error','error_variance','settle_time_s']:
                    vs=[x[k] for x in ml]; mv=sum(vs)/len(vs)
                    sv=math.sqrt(sum((v-mv)**2 for v in vs)/max(len(vs)-1,1))
                    av[k+'_std']=round(sv,4)
                gs[lb]=av
            s[gk]=gs
        return s

    def _conclude(self, summary):
        def gc(gk):
            g=summary.get(gk,{}); c=g.get('clean',{})
            return {'mean_error':c.get('mean_error',999),'fitness':c.get('fitness_score',0),
                    'settle_time':c.get('settle_time_s',999),'osc_freq':c.get('osc_freq',999),
                    'pwm_change':c.get('mean_pwm_change',999)}
        def gn(gk):
            g=summary.get(gk,{}); n=g.get('noisy',{})
            return {'mean_error':n.get('mean_error',999),'lost_pct':n.get('lost_pct',999)}
        a=gc('A_baseline'); b=gc('B_adaptive'); c=gc('C_control')
        an=gn('A_baseline'); bn=gn('B_adaptive')
        sc={'A':0,'B':0,'C':0}; reasons=[]
        if b['mean_error']<a['mean_error']:
            sc['B']+=2; reasons.append('B误差更低({:.3f}<{:.3f})'.format(b['mean_error'],a['mean_error']))
        elif b['mean_error']>a['mean_error']:
            sc['A']+=2; reasons.append('A误差更低({:.3f}<{:.3f})'.format(a['mean_error'],b['mean_error']))
        else: sc['A']+=1; sc['B']+=1
        if b['settle_time']<a['settle_time']:
            sc['B']+=1; reasons.append('B收敛更快')
        elif b['settle_time']>a['settle_time']:
            sc['A']+=1; reasons.append('A收敛更快')
        if b['pwm_change']<a['pwm_change']:
            sc['B']+=1; reasons.append('B控制更平滑')
        elif b['pwm_change']>a['pwm_change']*1.1:
            sc['A']+=1; reasons.append('B控制抖动更大')
        if bn['mean_error']<an['mean_error']:
            sc['B']+=1; reasons.append('B抗噪更强')
        elif bn['mean_error']>an['mean_error']*1.1:
            sc['A']+=1; reasons.append('A抗噪更强')
        if b['osc_freq']<a['osc_freq']:
            sc['B']+=1; reasons.append('B震荡更少')
        elif b['osc_freq']>a['osc_freq']*1.2:
            sc['A']+=1; reasons.append('B震荡更多')
        w=max(sc,key=sc.get)
        if w=='B' and sc['B']-sc['A']>=2:
            v='Adaptive PID 显著优于 Baseline'; cf=min(95,60+(sc['B']-sc['A'])*10)
        elif w=='B' and sc['B']>sc['A']:
            v='Adaptive PID 略优于 Baseline'; cf=min(80,50+(sc['B']-sc['A'])*10)
        elif w=='A':
            v='Baseline PID 优于 Adaptive PID'; cf=min(85,55+(sc['A']-sc['B'])*10)
        else:
            v='两组性能接近, 无显著差异'; cf=50
        warns=[]
        if b['pwm_change']>a['pwm_change']*1.3: warns.append('Adaptive PID 存在抖动放大风险')
        if b['osc_freq']>a['osc_freq']*1.5: warns.append('Adaptive PID 存在过调风险')
        return {'winner':w,'verdict':v,'confidence':cf,'scores':sc,'reasons':reasons,'warnings':warns}

    def print_report(self, results):
        print()
        print("=" * 60)
        print("  Adaptive PID A/B/C Experiment Report")
        print("=" * 60)
        p=results.get('params',{}); c=results.get('config',{})
        print("  PID: Kp={} Ki={} Kd={}".format(p.get('kp'),p.get('ki'),p.get('kd')))
        print("  Ticks={} Seeds={} dt={}".format(c.get('max_ticks'),c.get('seeds'),c.get('dt')))
        sm=results.get('summary',{})
        for gk in ['A_baseline','B_adaptive','C_control']:
            g=results.get(gk,{})
            print()
            print("  --- {} ---".format(g.get('label',gk)))
            for cl,m in sm.get(gk,{}).items():
                print("    [{}] fitness={:.1f} err={:.3f} settle={:.2f}s osc={:.2f} pwm={:.1f} lost={:.1f}%".format(
                    cl,m.get('fitness_score',0),m.get('mean_error',0),
                    m.get('settle_time_s',0),m.get('osc_freq',0),
                    m.get('mean_pwm_change',0),m.get('lost_pct',0)))
        co=results.get('conclusion',{})
        print()
        print("  --- Conclusion ---")
        print("  Winner: Group {}".format(co.get('winner','?')))
        print("  Verdict: {}".format(co.get('verdict','')))
        print("  Confidence: {}/100".format(co.get('confidence',0)))
        for r in co.get('reasons',[]): print("    + {}".format(r))
        for w in co.get('warnings',[]): print("    ! {}".format(w))
        print()
        print("=" * 60)

    def save_report(self, results, filepath):
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath,'w',encoding='utf-8') as f:
            json.dump(results,f,indent=2,ensure_ascii=False,default=str)
        print("[ABTest] Saved:", filepath)