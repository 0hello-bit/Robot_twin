# -*- coding: utf-8 -*-
import sys, os, math, glob, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pygame
import numpy as np
try:
    import cv2
except ImportError:
    print("Need opencv-python"); sys.exit(1)
import config as cfg
from simulator.car import MecanumCar
from simulator.map import TrackMap
from simulator.timing import ControlTickTimer
from simulator.camera_simulator import VirtualK230Camera
from control.camera_line_follow import CameraLineFollower
from tracks.curriculum_track_generator import CurriculumTrackGenerator


class RealInputSource:
    def __init__(self):
        self.source_type = None
        self.current_frame = None
        self._cap = None
        self._image_files = []
        self._image_index = 0
        self._paused = False
        self._frame_count = 0
        self._total_frames = 0
        self._speed = 1.0
        self._last_read_time = 0
        self._display_name = ""

    def open_image(self, fp):
        if not os.path.exists(fp): return False
        img = cv2.imread(fp)
        if img is None: return False
        self.current_frame = img
        self.source_type = "image"
        self._display_name = os.path.basename(fp)
        self._paused = True
        print("Loaded image:", fp)
        return True

    def open_video(self, fp):
        if fp is None or fp == "0":
            return self.open_webcam(0)
        if not os.path.exists(fp): return False
        cap = cv2.VideoCapture(fp)
        if not cap.isOpened(): return False
        self._cap = cap
        self.source_type = "video"
        self._total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._display_name = os.path.basename(fp)
        self._paused = False
        self._speed = 1.0
        self._frame_count = 0
        print("Loaded video:", fp)
        return True

    def open_webcam(self, idx=0):
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened(): return False
        self._cap = cap
        self.source_type = "webcam"
        self._total_frames = -1
        self._display_name = "Webcam %d" % idx
        self._paused = False
        self._speed = 1.0
        self._frame_count = 0
        print("Opened webcam:", idx)
        return True

    def read(self):
        if self.source_type is None: return None
        if self.source_type == "image": return self.current_frame
        if self.source_type in ("video", "webcam"):
            if self._paused: return self.current_frame
            now = time.monotonic()
            interval = 0.033 / max(self._speed, 0.1)
            if now - self._last_read_time < interval:
                return self.current_frame
            self._last_read_time = now
            ret, frame = self._cap.read()
            if ret:
                self.current_frame = frame
                self._frame_count += 1
                return frame
            elif self.source_type == "video":
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self._frame_count = 0
                ret, frame = self._cap.read()
                if ret:
                    self.current_frame = frame
                    return frame
            return self.current_frame
        return None

    def toggle_pause(self):
        self._paused = not self._paused
        return self._paused

    def next_frame(self):
        if self.source_type in ("video", "webcam") and self._cap:
            ret, frame = self._cap.read()
            if ret:
                self.current_frame = frame
                self._frame_count += 1

    def set_speed(self, s):
        self._speed = max(0.1, min(5.0, s))

    def get_speed(self):
        return self._speed

    def is_active(self):
        return self.source_type is not None

    def is_paused(self):
        return self._paused

    def get_info(self):
        if self.source_type is None: return "No input"
        info = self._display_name
        if self.source_type == "video":
            info += " [%d/%d]" % (self._frame_count, self._total_frames)
        if self._paused: info += " [PAUSED]"
        if self.source_type not in ("image",):
            info += " x%.1f" % self._speed
        return info

    def close(self):
        if self._cap: self._cap.release(); self._cap = None
        self.source_type = None
        self.current_frame = None


class PerspectiveCamera:
    def __init__(self, sw, sh, height=180, dist=120, fov_deg=70):
        self.sw, self.sh = sw, sh
        self.height = height
        self.distance = dist
        self.fov = math.radians(fov_deg)
        self.focal = (sw / 2) / math.tan(self.fov / 2)
        self.horizon_y = sh * 0.35

    def project(self, wx, wy, cx, cy, ca):
        dx, dy = wx - cx, wy - cy
        cos_a = math.cos(-math.radians(ca))
        sin_a = math.sin(-math.radians(ca))
        rx = dx * cos_a - dy * sin_a
        rz = dx * sin_a + dy * cos_a
        if rz < 10: return None
        sx = self.sw / 2 + rx * self.focal / rz
        sy = self.horizon_y + self.height * self.focal / rz
        return (sx, sy, rz)

    def project_car(self, car_x, car_y, car_a, cx, cy, ca):
        r = self.project(car_x, car_y, cx, cy, ca)
        if r is None: return None
        return (r[0], r[1], r[2], self.focal / r[2])


def draw_ground(sub, cam, sw, sh):
    for y in range(int(cam.horizon_y)):
        t = y / max(cam.horizon_y, 1)
        pygame.draw.line(sub, (int(40+80*t), int(60+100*t), int(120+80*t)),
                         (0, y), (sw, y))
    for y in range(int(cam.horizon_y), sh):
        t = (y - cam.horizon_y) / max(sh - cam.horizon_y, 1)
        pygame.draw.line(sub, (int(60+40*t), int(80+50*t), int(50+30*t)),
                         (0, y), (sw, y))


def draw_track_3d(sub, segs, cam, cx, cy, ca):
    proj = []
    for s in segs:
        p1 = cam.project(s[0], s[1], cx, cy, ca)
        p2 = cam.project(s[2], s[3], cx, cy, ca)
        if p1 and p2:
            proj.append((p1, p2, (p1[2]+p2[2])/2))
    proj.sort(key=lambda x: -x[2])
    for p1, p2, d in proj:
        th = max(1, min(20, int(cfg.TRACK_WIDTH * cam.focal / d * 0.15)))
        f = min(1.0, d / 800)
        c = (int(30+50*f), int(30+50*f), int(30+60*f))
        ce = (max(0,c[0]-20), max(0,c[1]-20), max(0,c[2]-20))
        pygame.draw.line(sub, ce, (int(p1[0]),int(p1[1])), (int(p2[0]),int(p2[1])), th+3)
        pygame.draw.line(sub, c, (int(p1[0]),int(p1[1])), (int(p2[0]),int(p2[1])), th)


def draw_car_3d(sub, car, cam, cx, cy, ca):
    r = cam.project_car(car.x, car.y, car.angle, cx, cy, ca)
    if r is None or r[2] < 20: return
    sx, sy, depth, sc = r
    a = math.radians(car.angle)
    co, si = math.cos(a), math.sin(a)
    hw, hl = cfg.CAR_WIDTH/2, cfg.CAR_LENGTH/2
    cw = [(car.x+hl*co-hw*si, car.y+hl*si+hw*co),
          (car.x+hl*co+hw*si, car.y+hl*si-hw*co),
          (car.x-hl*co+hw*si, car.y-hl*si-hw*co),
          (car.x-hl*co-hw*si, car.y-hl*si+hw*co)]
    sc_pts = []
    for wx, wy in cw:
        p = cam.project(wx, wy, cx, cy, ca)
        if p is None: return
        sc_pts.append((int(p[0]), int(p[1])))
    pygame.draw.polygon(sub, (20,20,30), [(x+2,y+3) for x,y in sc_pts])
    pygame.draw.polygon(sub, (40,80,200), sc_pts)
    pygame.draw.polygon(sub, (80,140,255), sc_pts, 2)
    fc = ((sc_pts[0][0]+sc_pts[1][0])//2, (sc_pts[0][1]+sc_pts[1][1])//2)
    tip = cam.project(car.x+hl*1.2*co, car.y+hl*1.2*si, cx, cy, ca)
    if tip:
        pygame.draw.line(sub, (255,80,80), fc, (int(tip[0]),int(tip[1])), 2)
    for off in cfg.SENSOR_OFFSETS:
        sp = cam.project(car.x+cfg.SENSOR_FRONT*co-off*si,
                         car.y+cfg.SENSOR_FRONT*si+off*co, cx, cy, ca)
        if sp and sp[2] > 10:
            pygame.draw.circle(sub, (50,220,50), (int(sp[0]),int(sp[1])), max(2,int(4*sc)))


class Sim3D:
    def __init__(self, level=1):
        pygame.init()
        self.cw3d, self.ch3d = 960, 640
        self.kw, self.kh = 320, 240
        self.ks = 2
        self.kdw = self.kw * self.ks
        self.tw = self.cw3d + self.kdw
        self.th = max(self.ch3d, self.kh * self.ks + 120)
        self.screen = pygame.display.set_mode((self.tw, self.th))
        pygame.display.set_caption("STM32 3D Digital Twin v3")
        self.clock = pygame.time.Clock()
        self.cam3d = PerspectiveCamera(self.cw3d, self.ch3d, 160, 100, 65)
        self.tg = CurriculumTrackGenerator()
        self.tl = level
        self._build_track(level)
        self.car = MecanumCar(*self.start_pos)
        self.k230 = VirtualK230Camera((self.kw, self.kh), 60, 30, 25, 250)
        self.ctrl = CameraLineFollower(self.k230, cfg.DEFAULT_KP, cfg.DEFAULT_KI, cfg.DEFAULT_KD, 250)
        self.timer = ControlTickTimer(cfg.DEFAULT_CONTROL_HZ)
        self.real = RealInputSource()
        self.running = True
        self.auto = True
        self.show_dbg = True
        self.trail = []
        self.info_t = ""
        self.info_timer = 0.0
        self.font = pygame.font.SysFont("Arial", 16, bold=True)
        self.font_sm = pygame.font.SysFont("Consolas", 12)
        print("=" * 50)
        print("  STM32 3D Digital Twin v3")
        print("  L=Image O=Video P=Pause N=Next ,/.=Speed")
        print("  F/G=FOV H/J=Height T/Y=Tilt V/B=Dist")
        print("=" * 50)

    def _build_track(self, level):
        pts = self.tg.get_track(level)
        self.track_pts = np.array(pts)
        self.track = TrackMap()
        self.track.add_polyline(pts, close=True)
        s = self.tg.get_start_pos()
        self.start_pos = (s[0], s[1], s[2]) if s else (pts[0][0], pts[0][1], 0.0)
        self.tl = level

    def run(self):
        while self.running:
            dt = self.clock.tick(cfg.FPS) / 1000.0
            self._events()
            if self.auto and self.timer.tick():
                self._control()
            self.car.update(dt)
            self.trail.append((self.car.x, self.car.y))
            if len(self.trail) > 3000: self.trail.pop(0)
            self._render()
        self.real.close()
        pygame.quit()

    def _events(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT: self.running = False
            elif e.type == pygame.KEYDOWN:
                k = e.key
                if k == pygame.K_ESCAPE: self.running = False
                elif k == pygame.K_SPACE: self.auto = not self.auto
                elif k == pygame.K_r: self.car.reset(*self.start_pos); self.ctrl.reset(); self.trail.clear()
                elif k == pygame.K_TAB: self.show_dbg = not self.show_dbg
                elif k == pygame.K_UP: self.ctrl.set_pid_gains(kp=self.ctrl.pid.kp+0.05); self._info("Kp: %.3f" % self.ctrl.pid.kp)
                elif k == pygame.K_DOWN: self.ctrl.set_pid_gains(kp=max(0,self.ctrl.pid.kp-0.05)); self._info("Kp: %.3f" % self.ctrl.pid.kp)
                elif k == pygame.K_RIGHT: self.ctrl.set_pid_gains(kd=self.ctrl.pid.kd+0.01); self._info("Kd: %.3f" % self.ctrl.pid.kd)
                elif k == pygame.K_LEFT: self.ctrl.set_pid_gains(kd=max(0,self.ctrl.pid.kd-0.01)); self._info("Kd: %.3f" % self.ctrl.pid.kd)
                elif k in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                    self._build_track(k - pygame.K_0); self.trail.clear(); self.ctrl.reset(); self.car.reset(*self.start_pos); self._info("Track L%d" % (k-pygame.K_0))
                elif k == pygame.K_f: self.k230.fov = math.radians(min(120, math.degrees(self.k230.fov)+5)); self.k230._init_projection(); self._info("FOV: %.0f" % math.degrees(self.k230.fov))
                elif k == pygame.K_g: self.k230.fov = math.radians(max(20, math.degrees(self.k230.fov)-5)); self.k230._init_projection(); self._info("FOV: %.0f" % math.degrees(self.k230.fov))
                elif k == pygame.K_h: self.k230.mount_height = min(80, self.k230.mount_height+3); self._info("H: %d" % self.k230.mount_height)
                elif k == pygame.K_j: self.k230.mount_height = max(5, self.k230.mount_height-3); self._info("H: %d" % self.k230.mount_height)
                elif k == pygame.K_t: self.k230.tilt = math.radians(min(60, math.degrees(self.k230.tilt)+3)); self._info("Tilt: %.0f" % math.degrees(self.k230.tilt))
                elif k == pygame.K_y: self.k230.tilt = math.radians(max(0, math.degrees(self.k230.tilt)-3)); self._info("Tilt: %.0f" % math.degrees(self.k230.tilt))
                elif k == pygame.K_v: self.k230.view_distance = min(600, self.k230.view_distance+30); self._info("Dist: %d" % self.k230.view_distance)
                elif k == pygame.K_b: self.k230.view_distance = max(50, self.k230.view_distance-30); self._info("Dist: %d" % self.k230.view_distance)
                elif k == pygame.K_l: self._load_img()
                elif k == pygame.K_o: self._load_vid()
                elif k == pygame.K_p: p = self.real.toggle_pause(); self._info("Video: %s" % ("PAUSED" if p else "PLAYING"))
                elif k == pygame.K_n: self.real.next_frame()
                elif k == pygame.K_COMMA: self.real.set_speed(self.real.get_speed()-0.25); self._info("Speed: x%.2f" % self.real.get_speed())
                elif k == pygame.K_PERIOD: self.real.set_speed(self.real.get_speed()+0.25); self._info("Speed: x%.2f" % self.real.get_speed())

    def _load_img(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
            r = tk.Tk(); r.withdraw()
            fp = filedialog.askopenfilename(title="Select image", filetypes=[("Images","*.jpg *.jpeg *.png *.bmp")])
            r.destroy()
            if fp and self.real.open_image(fp): self._info("Image: %s" % os.path.basename(fp))
        except Exception as e: print("Dialog error:", e)

    def _load_vid(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
            r = tk.Tk(); r.withdraw()
            fp = filedialog.askopenfilename(title="Select video (cancel=webcam)", filetypes=[("Videos","*.mp4 *.avi *.mkv *.mov")])
            r.destroy()
            if fp:
                if self.real.open_video(fp): self._info("Video: %s" % os.path.basename(fp))
            else:
                if self.real.open_webcam(0): self._info("Webcam opened")
                else: self._info("No webcam found")
        except Exception as e: print("Dialog error:", e)

    def _control(self):
        lp, rp = self.ctrl.step(self.car.x, self.car.y, self.car.angle, self.track_pts, self.timer.get_control_dt())
        ln = (lp / 999.0) * 2.0 - 1.0
        rn = (rp / 999.0) * 2.0 - 1.0
        self.car.drive(ln, rn)

    def _info(self, t, d=2.0):
        self.info_t = t; self.info_timer = d

    def _render(self):
        self.screen.fill((0,0,0))
        self._render_3d()
        self._render_right()
        self._render_hud()
        if self.info_timer > 0:
            self.info_timer -= cfg.PHYSICS_DT
            f = pygame.font.SysFont("Arial", 18, bold=True)
            txt = f.render(self.info_t, True, (255,255,255))
            bg = pygame.Surface((txt.get_width()+20, txt.get_height()+10)); bg.fill((20,25,35)); bg.set_alpha(200)
            cx = self.cw3d // 2
            self.screen.blit(bg, (cx-bg.get_width()//2, 40))
            self.screen.blit(txt, (cx-txt.get_width()//2, 45))
        pygame.display.flip()

    def _render_3d(self):
        sub = self.screen.subsurface((0, 0, self.cw3d, self.ch3d))
        draw_ground(sub, self.cam3d, self.cw3d, self.ch3d)
        cx = self.car.x - self.cam3d.distance * math.cos(math.radians(self.car.angle))
        cy = self.car.y - self.cam3d.distance * math.sin(math.radians(self.car.angle))
        for i in range(1, len(self.trail)):
            t = i / len(self.trail)
            p = self.cam3d.project(self.trail[i][0], self.trail[i][1], cx, cy, self.car.angle)
            if p and p[2] > 10:
                a = t * 0.6
                c = (max(0,min(255,int(100+80*a))), max(0,min(255,int(150+50*a))), max(0,min(255,int(255*a))))
                pygame.draw.circle(sub, c, (int(p[0]),int(p[1])), max(1,int(3*self.cam3d.focal/p[2])))
        draw_track_3d(sub, self.track.segments, self.cam3d, cx, cy, self.car.angle)
        draw_car_3d(sub, self.car, self.cam3d, cx, cy, self.car.angle)
        sub.blit(self.font.render("3D VIEW", True, (200,200,220)), (10, 8))

    def _render_right(self):
        xo = self.cw3d
        pw = self.kdw
        pygame.draw.rect(self.screen, (0,0,0), (xo, 0, pw, self.th))
        yo = 30
        detection = {}
        if self.real.is_active():
            frame = self.real.read()
            if frame is not None:
                h, w = frame.shape[:2]
                sc = min(pw/w, (self.kh*self.ks)/h)
                disp = cv2.resize(frame, (int(w*sc), int(h*sc)))
                rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB) if len(disp.shape)==3 else cv2.cvtColor(disp, cv2.COLOR_GRAY2RGB)
                rgb = np.transpose(rgb, (1,0,2))
                self.screen.blit(pygame.surfarray.make_surface(rgb), (xo, yo))
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if len(frame.shape)==3 else frame
                detection = self.k230.detect_line(gray)
                self.screen.blit(self.font.render("REAL INPUT", True, (255,200,50)), (xo+10, 5))
                self.screen.blit(self.font_sm.render(self.real.get_info(), True, (200,180,100)), (xo+130, 8))
            else:
                self.screen.blit(self.font.render("REAL INPUT (waiting)", True, (255,100,50)), (xo+10, 5))
        else:
            ov, detection = self.k230.render_with_overlay(self.car.x, self.car.y, self.car.angle, self.track_pts)
            rgb = cv2.cvtColor(ov, cv2.COLOR_BGR2RGB) if len(ov.shape)==3 else cv2.cvtColor(ov, cv2.COLOR_GRAY2RGB)
            rgb = np.transpose(rgb, (1,0,2))
            sf = pygame.surfarray.make_surface(rgb)
            sf = pygame.transform.scale(sf, (pw, self.kh*self.ks))
            self.screen.blit(sf, (xo, yo))
            self.screen.blit(self.font.render("K230 SIM", True, (100,200,255)), (xo+10, 5))
        pygame.draw.rect(self.screen, (80,80,100), (xo, yo, pw, self.kh*self.ks), 2)
        by = yo + self.kh*self.ks + 8
        ok = detection.get("line_detected", False)
        c = (50,220,50) if ok else (220,50,50)
        self.screen.blit(self.font_sm.render("Line: %s  Conf: %.2f" % ("YES" if ok else "NO", detection.get("confidence",0)), True, c), (xo+10, by))
        inf = self.ctrl.get_debug_info()
        self.screen.blit(self.font_sm.render("Err:%.3f Kp:%.3f Kd:%.3f" % (inf["error_normalized"], self.ctrl.pid.kp, self.ctrl.pid.kd), True, (180,180,200)), (xo+10, by+18))
        ci = "FOV:%.0f H:%d Tilt:%.0f Dist:%d" % (math.degrees(self.k230.fov), self.k230.mount_height, math.degrees(self.k230.tilt), self.k230.view_distance)
        self.screen.blit(self.font_sm.render(ci, True, (100,200,255)), (xo+10, by+36))
        self.screen.blit(self.font_sm.render("F/G=FOV H/J=Ht T/Y=Tilt V/B=Dist", True, (80,80,110)), (xo+10, by+54))
        if self.real.is_active():
            self.screen.blit(self.font_sm.render("P=Pause N=Next ,/.=Speed", True, (200,180,80)), (xo+10, by+72))

    def _render_hud(self):
        by = self.th - 32
        pygame.draw.rect(self.screen, (15,18,25), (0, by, self.tw, 32))
        md = "AUTO" if self.auto else "MANUAL"
        mc = (50,220,50) if self.auto else (220,200,50)
        ts = [("L%d %s" % (self.tl, md), mc), ("R=Reset SPACE=Pause 1-4=Track", (130,130,150)), ("L=Image O=Video P=Pause N=Next ,/.=Speed", (180,140,60)), ("ESC=Quit", (100,100,120))]
        x = 15
        for t, c in ts:
            self.screen.blit(self.font_sm.render(t, True, c), (x, by+9)); x += self.font_sm.render(t, True, c).get_width() + 25


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--level", type=int, default=1)
    pa.add_argument("--image", type=str, default=None)
    pa.add_argument("--video", type=str, default=None)
    pa.add_argument("--webcam", type=int, default=None)
    a = pa.parse_args()
    sim = Sim3D(a.level)
    if a.image: sim.real.open_image(a.image)
    if a.video: sim.real.open_video(a.video)
    if a.webcam is not None: sim.real.open_webcam(a.webcam)
    sim.run()

if __name__ == "__main__":
    main()
