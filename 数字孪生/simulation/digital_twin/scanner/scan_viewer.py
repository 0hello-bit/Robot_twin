# -*- coding: utf-8 -*-
"""
scan_viewer.py - 3D scan viewer using pyglet + OpenGL

Renders loaded 3D scans with camera controls.
Can overlay detected track and car position.

Usage:
    from scanner.scan_viewer import ScanViewer
    viewer = ScanViewer()
    viewer.set_mesh(vertices, faces)
    viewer.set_track(track_points_3d)
    viewer.run()
"""

import math
import numpy as np

try:
    import pyglet
    from pyglet.gl import *
    HAS_PYGLET = True
except ImportError:
    HAS_PYGLET = False

try:
    import trimesh
    HAS_TRIMESH = True
except ImportError:
    HAS_TRIMESH = False


class Camera3D:
    """Orbit camera for 3D viewing."""

    def __init__(self):
        self.theta = 45.0
        self.phi = 30.0
        self.distance = 5.0
        self.target = np.array([0.0, 0.0, 0.0])
        self.fov = 60.0
        self.near = 0.01
        self.far = 100.0

    def get_eye(self):
        t = math.radians(self.theta)
        p = math.radians(self.phi)
        d = self.distance
        x = self.target[0] + d * math.cos(p) * math.cos(t)
        y = self.target[1] + d * math.cos(p) * math.sin(t)
        z = self.target[2] + d * math.sin(p)
        return np.array([x, y, z])

    def rotate(self, dtheta, dphi):
        self.theta += dtheta
        self.phi = max(-89, min(89, self.phi + dphi))

    def zoom(self, factor):
        self.distance = max(0.1, self.distance * factor)

    def pan(self, dx, dy):
        t = math.radians(self.theta)
        right = np.array([-math.sin(t), math.cos(t), 0])
        forward = np.array([0, 0, 1])
        self.target += right * dx + forward * dy


class ScanViewer:
    """
    3D viewer for scanned environments.
    
    Controls:
        Mouse drag = rotate
        Scroll = zoom
        Right drag = pan
        R = reset camera
        T = toggle track
        C = toggle car
        ESC = quit
    """

    def __init__(self, width=1280, height=720, title="3D Scan Viewer"):
        if not HAS_PYGLET:
            raise RuntimeError("pyglet required")

        self.width = width
        self.height = height
        self.window = pyglet.window.Window(width, height, caption=title,
                                           resizable=True)
        self.camera = Camera3D()
        self.show_track = True
        self.show_car = True
        self.show_mesh = True

        self.vertices = None
        self.faces = None
        self.track_points = None
        self.car_position = None
        self.car_angle = 0.0

        self._vlist = None
        self._track_vlist = None

        self._setup_gl()
        self._setup_input()

    def _setup_gl(self):
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

        glLightfv(GL_LIGHT0, GL_POSITION, (0.0, 0.0, 10.0, 1.0))
        glLightfv(GL_LIGHT0, GL_AMBIENT, (0.3, 0.3, 0.3, 1.0))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (0.8, 0.8, 0.8, 1.0))

        glClearColor(0.15, 0.18, 0.22, 1.0)

    def _setup_input(self):
        self._last_mouse = None
        self._mouse_buttons = set()

        @self.window.event
        def on_mouse_press(x, y, button, modifiers):
            self._last_mouse = (x, y)
            self._mouse_buttons.add(button)

        @self.window.event
        def on_mouse_release(x, y, button, modifiers):
            self._mouse_buttons.discard(button)
            self._last_mouse = None

        @self.window.event
        def on_mouse_drag(x, y, dx, dy, button, modifiers):
            if self._last_mouse:
                ox, oy = self._last_mouse
                if button == pyglet.window.mouse.LEFT:
                    self.camera.rotate((x - ox) * 0.5, (y - oy) * 0.5)
                elif button == pyglet.window.mouse.RIGHT:
                    self.camera.pan(-dx * 0.005, dy * 0.005)
                self._last_mouse = (x, y)

        @self.window.event
        def on_mouse_scroll(x, y, scroll_x, scroll_y):
            factor = 0.9 if scroll_y > 0 else 1.1
            self.camera.zoom(factor)

        @self.window.event
        def on_key_press(symbol, modifiers):
            if symbol == pyglet.window.key.ESCAPE:
                self.window.close()
            elif symbol == pyglet.window.key.R:
                self.camera = Camera3D()
            elif symbol == pyglet.window.key.T:
                self.show_track = not self.show_track
            elif symbol == pyglet.window.key.C:
                self.show_car = not self.show_car
            elif symbol == pyglet.window.key.M:
                self.show_mesh = not self.show_mesh

        @self.window.event
        def on_resize(w, h):
            self.width, self.height = w, h
            glViewport(0, 0, w, h)
            self._setup_projection()

    def _setup_projection(self):
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        aspect = self.width / max(self.height, 1)
        gluPerspective(self.camera.fov, aspect,
                       self.camera.near, self.camera.far)
        glMatrixMode(GL_MODELVIEW)

    def set_mesh(self, vertices, faces):
        self.vertices = np.array(vertices, dtype=np.float32)
        self.faces = np.array(faces, dtype=np.int32) if faces is not None and len(faces) > 0 else None
        if self.vertices is not None and len(self.vertices) > 0:
            center = self.vertices.mean(axis=0)
            extent = self.vertices.max(axis=0) - self.vertices.min(axis=0)
            self.camera.target = center
            self.camera.distance = float(extent.max()) * 1.5

    def set_track(self, track_points_3d):
        if track_points_3d is not None and len(track_points_3d) > 0:
            self.track_points = np.array(track_points_3d, dtype=np.float32)
        else:
            self.track_points = None

    def set_car(self, x, y, z, angle):
        self.car_position = np.array([x, y, z], dtype=np.float32)
        self.car_angle = angle

    def _draw_mesh(self):
        if self.vertices is None or self.faces is None:
            return
        if not self.show_mesh:
            return

        verts = self.vertices
        faces = self.faces

        glEnable(GL_NORMALS)
        glColor3f(0.6, 0.65, 0.7)

        glBegin(GL_TRIANGLES)
        for face in faces:
            v0, v1, v2 = verts[face[0]], verts[face[1]], verts[face[2]]
            normal = np.cross(v1 - v0, v2 - v0)
            nlen = np.linalg.norm(normal)
            if nlen > 1e-10:
                normal /= nlen
            glNormal3f(*normal)
            glVertex3f(*v0)
            glVertex3f(*v1)
            glVertex3f(*v2)
        glEnd()

    def _draw_track(self):
        if self.track_points is None or not self.show_track:
            return
        pts = self.track_points

        glDisable(GL_LIGHTING)
        glLineWidth(4.0)
        glColor3f(1.0, 0.3, 0.1)
        glBegin(GL_LINE_STRIP)
        for p in pts:
            glVertex3f(p[0], p[1], p[2] + 0.005)
        glEnd()
        glLineWidth(1.0)
        glEnable(GL_LIGHTING)

    def _draw_car(self):
        if self.car_position is None or not self.show_car:
            return
        p = self.car_position
        a = math.radians(self.car_angle)

        glDisable(GL_LIGHTING)

        # Car body
        glPushMatrix()
        glTranslatef(p[0], p[1], p[2] + 0.02)
        glRotatef(self.car_angle, 0, 0, 1)

        glColor3f(0.2, 0.5, 1.0)
        glLineWidth(3.0)

        # Simple car shape
        l, w = 0.15, 0.10
        glBegin(GL_LINE_LOOP)
        glVertex3f(-l, -w, 0)
        glVertex3f(l, -w, 0)
        glVertex3f(l, w, 0)
        glVertex3f(-l, w, 0)
        glEnd()

        # Fill
        glColor4f(0.2, 0.5, 1.0, 0.6)
        glBegin(GL_QUADS)
        glVertex3f(-l, -w, 0)
        glVertex3f(l, -w, 0)
        glVertex3f(l, w, 0)
        glVertex3f(-l, w, 0)
        glEnd()

        # Direction arrow
        glColor3f(1.0, 0.2, 0.2)
        glBegin(GL_LINES)
        glVertex3f(0, 0, 0)
        glVertex3f(l + 0.05, 0, 0)
        glEnd()

        glPopMatrix()
        glEnable(GL_LIGHTING)

    def _draw_grid(self):
        glDisable(GL_LIGHTING)
        glColor3f(0.25, 0.28, 0.32)
        glLineWidth(0.5)
        size = 5.0
        step = 0.5
        glBegin(GL_LINES)
        x = -size
        while x <= size:
            glVertex3f(x, -size, 0)
            glVertex3f(x, size, 0)
            x += step
        y = -size
        while y <= size:
            glVertex3f(-size, y, 0)
            glVertex3f(size, y, 0)
            y += step
        glEnd()
        glEnable(GL_LIGHTING)

    def run(self):
        self._setup_projection()

        @self.window.event
        def on_draw():
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glLoadIdentity()
            eye = self.camera.get_eye()
            gluLookAt(eye[0], eye[1], eye[2],
                      self.camera.target[0], self.camera.target[1], self.camera.target[2],
                      0, 0, 1)

            self._draw_grid()
            self._draw_mesh()
            self._draw_track()
            self._draw_car()

            # HUD text
            label = pyglet.text.Label(
                "T=Track C=Car M=Mesh R=Reset ESC=Quit",
                font_name='Arial', font_size=12,
                x=10, y=self.height - 25, color=(200, 200, 200, 200))
            label.draw()

        pyglet.app.run()
