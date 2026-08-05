# -*- coding: utf-8 -*-
"""
scan_loader.py - Load 3D scan files (OBJ, PLY, GLB/GLTF)

Uses trimesh to load 3D models from phone scans.
Common scanning apps that export compatible formats:
    - Polycam (iOS) -> OBJ, PLY, GLTF
    - Scaniverse (iOS/Android) -> OBJ, PLY, GLTF
    - 3D Scanner App (iOS) -> OBJ, PLY
    - RoomScan LiDAR (iOS) -> OBJ
    - KIRI Engine (Android) -> OBJ, PLY, GLTF

Usage:
    from scanner.scan_loader import ScanLoader
    loader = ScanLoader()
    mesh = loader.load("room_scan.obj")
    points = loader.get_point_cloud(mesh, density=100000)
    vertices, faces = loader.get_mesh_data(mesh)
"""

import os
import numpy as np

try:
    import trimesh
    HAS_TRIMESH = True
except ImportError:
    HAS_TRIMESH = False
    print("[ScanLoader] trimesh not installed. Run: pip install trimesh")


class ScanLoader:
    """
    Load 3D scan files and convert to numpy arrays.
    
    Supports:
        - .obj  (Wavefront OBJ)
        - .ply  (Stanford PLY)
        - .glb/.gltf (glTF binary/text)
        - .stl  (STL)
        - .off  (Object File Format)
    """

    SUPPORTED = ('.obj', '.ply', '.glb', '.gltf', '.stl', '.off')

    def __init__(self):
        self.last_mesh = None
        self.last_info = {}

    def load(self, filepath):
        """
        Load a 3D model file.
        
        Args:
            filepath: path to .obj/.ply/.glb file
            
        Returns:
            trimesh.Trimesh object, or None on failure
        """
        if not HAS_TRIMESH:
            print("[ScanLoader] Cannot load: trimesh not installed")
            return None

        if not os.path.exists(filepath):
            print("[ScanLoader] File not found:", filepath)
            return None

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in self.SUPPORTED:
            print("[ScanLoader] Unsupported format:", ext)
            return None

        try:
            scene_or_mesh = trimesh.load(filepath, force='mesh')
            if isinstance(scene_or_mesh, trimesh.Scene):
                mesh = trimesh.util.concatenate(
                    list(scene_or_mesh.geometry.values()))
            else:
                mesh = scene_or_mesh
            self.last_mesh = mesh
            self.last_info = self._analyze(mesh)
            self._print_info()
            return mesh
        except Exception as e:
            print("[ScanLoader] Failed to load:", e)
            return None

    def _analyze(self, mesh):
        """Analyze mesh properties."""
        verts = mesh.vertices
        info = {
            'vertices': len(verts),
            'faces': len(mesh.faces) if hasattr(mesh, 'faces') else 0,
            'bounds_min': verts.min(axis=0).tolist(),
            'bounds_max': verts.max(axis=0).tolist(),
            'center': verts.mean(axis=0).tolist(),
            'extent': (verts.max(axis=0) - verts.min(axis=0)).tolist(),
            'has_normals': hasattr(mesh, 'vertex_normals'),
            'has_colors': hasattr(mesh, 'vertex_colors'),
        }
        return info

    def _print_info(self):
        i = self.last_info
        print("[ScanLoader] Loaded mesh:")
        print("  Vertices:", i['vertices'])
        print("  Faces:", i['faces'])
        print("  Bounds:", [round(x, 2) for x in i['bounds_min']],
              "->", [round(x, 2) for x in i['bounds_max']])
        print("  Size:", [round(x, 2) for x in i['extent']])

    def get_point_cloud(self, mesh=None, density=50000):
        """
        Sample point cloud from mesh surface.
        
        Args:
            mesh: trimesh object (uses last loaded if None)
            density: number of points to sample
            
        Returns:
            Nx3 numpy array of 3D points
        """
        if mesh is None:
            mesh = self.last_mesh
        if mesh is None:
            return np.zeros((0, 3))

        try:
            points, face_idx = trimesh.sample.sample_surface(mesh, density)
            return points
        except Exception:
            return np.array(mesh.vertices)

    def get_mesh_data(self, mesh=None):
        """
        Get vertices and faces as numpy arrays.
        
        Returns:
            (vertices, faces) where vertices is Nx3, faces is Mx3
        """
        if mesh is None:
            mesh = self.last_mesh
        if mesh is None:
            return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)

        vertices = np.array(mesh.vertices, dtype=np.float32)
        faces = np.array(mesh.faces, dtype=np.int32) if hasattr(mesh, 'faces') else np.zeros((0, 3), dtype=np.int32)
        return vertices, faces

    def get_normals(self, mesh=None):
        if mesh is None:
            mesh = self.last_mesh
        if mesh is None:
            return None
        if hasattr(mesh, 'vertex_normals'):
            return np.array(mesh.vertex_normals, dtype=np.float32)
        return None

    def get_bounds(self, mesh=None):
        if mesh is None:
            mesh = self.last_mesh
        if mesh is None:
            return None, None
        v = mesh.vertices
        return v.min(axis=0), v.max(axis=0)

    def center_and_scale(self, mesh=None, target_size=10.0):
        """
        Center mesh at origin and scale to target_size.
        Useful for normalizing phone scans of different scales.
        
        Returns:
            (center_offset, scale_factor)
        """
        if mesh is None:
            mesh = self.last_mesh
        if mesh is None:
            return np.zeros(3), 1.0

        verts = mesh.vertices
        center = verts.mean(axis=0)
        extent = verts.max(axis=0) - verts.min(axis=0)
        max_extent = extent.max()
        scale = target_size / max_extent if max_extent > 0 else 1.0

        mesh.vertices = (verts - center) * scale
        self.last_mesh = mesh
        self.last_info = self._analyze(mesh)
        return center, scale

    def export(self, mesh, filepath):
        """Export mesh to file."""
        if mesh is None:
            return False
        try:
            mesh.export(filepath)
            print("[ScanLoader] Exported to:", filepath)
            return True
        except Exception as e:
            print("[ScanLoader] Export failed:", e)
            return False
