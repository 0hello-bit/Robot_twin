# -*- coding: utf-8 -*-
"""
main_scan.py - 3D Scan -> Simulation Pipeline

Complete pipeline:
    1. Load phone 3D scan (OBJ/PLY/GLB)
    2. Extract floor plane
    3. Detect track line on floor
    4. Render 3D environment with track + car
    5. Run line-following simulation

Usage:
    # Load a real scan
    python main_scan.py --scan path/to/room.obj

    # Demo with generated test model
    python main_scan.py --demo

    # Just view the scan (no simulation)
    python main_scan.py --scan room.obj --view-only

Controls (in 3D viewer):
    Mouse drag  = Rotate camera
    Scroll      = Zoom
    Right drag  = Pan
    T           = Toggle track visibility
    C           = Toggle car
    M           = Toggle mesh
    R           = Reset camera
    SPACE       = Pause/Resume simulation
    ESC         = Quit
"""

import sys
import os
import math
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python required")
    sys.exit(1)


def create_demo_scan():
    """
    Generate a synthetic 3D scan for testing.
    Creates a flat floor with a curved track line.
    
    Returns: (vertices, faces) as numpy arrays
    """
    print("[Demo] Generating synthetic room scan...")

    # Floor plane (flat rectangle)
    floor_size = 3.0
    resolution = 0.01
    xs = np.arange(-floor_size, floor_size, resolution)
    ys = np.arange(-floor_size, floor_size, resolution)
    xx, yy = np.meshgrid(xs, ys)
    zz = np.zeros_like(xx)

    vertices_floor = np.column_stack([
        xx.flatten(), yy.flatten(), zz.flatten()
    ])

    # Add some wall vertices (simple box room)
    wall_h = 1.5
    wall_verts = []
    for x in np.arange(-floor_size, floor_size, resolution * 3):
        wall_verts.append([x, -floor_size, 0])
        wall_verts.append([x, -floor_size, wall_h])
        wall_verts.append([x, floor_size, 0])
        wall_verts.append([x, floor_size, wall_h])
        wall_verts.append([-floor_size, x, 0])
        wall_verts.append([-floor_size, x, wall_h])
        wall_verts.append([floor_size, x, 0])
        wall_verts.append([floor_size, x, wall_h])

    vertices_walls = np.array(wall_verts) if wall_verts else np.zeros((0, 3))

    # Add track line vertices (dark strip on floor)
    n_track = 500
    t = np.linspace(0, 2 * math.pi, n_track)
    # Oval track
    rx, ry = 1.8, 1.2
    track_x = rx * np.cos(t)
    track_y = ry * np.sin(t)
    track_z = np.zeros(n_track) + 0.001
    track_verts = np.column_stack([track_x, track_y, track_z])

    # All vertices
    vertices = np.vstack([vertices_floor, vertices_walls, track_verts])
    print("[Demo] Generated", len(vertices), "points")
    print("[Demo] Floor: %dx%d = %d points" % (len(xs), len(ys), len(vertices_floor)))
    print("[Demo] Track: %d points (oval: rx=%.1f ry=%.1f)" % (n_track, rx, ry))

    return vertices, None, track_verts


def run_pipeline(scan_path=None, demo=False, view_only=False):
    """Run the full scan-to-simulation pipeline."""
    from scanner.scan_loader import ScanLoader
    from scanner.floor_extractor import FloorExtractor
    from scanner.track_detector import TrackDetector

    loader = ScanLoader()
    extractor = FloorExtractor()
    detector = TrackDetector()

    track_3d = None
    vertices = None
    faces = None

    if demo:
        vertices, faces, track_3d = create_demo_scan()
    elif scan_path:
        print("\n=== Step 1: Load 3D Scan ===")
        mesh = loader.load(scan_path)
        if mesh is None:
            print("Failed to load scan")
            return
        vertices, faces = loader.get_mesh_data(mesh)
        points = loader.get_point_cloud(mesh, density=100000)

        print("\n=== Step 2: Extract Floor ===")
        floor_pts, normal, bounds = extractor.extract(points)
        if floor_pts is None:
            print("Failed to extract floor")
            return

        print("\n=== Step 3: Project to 2D ===")
        pts_2d, transform = extractor.project_to_2d(floor_pts, normal)
        floor_img, origin, scale = extractor.extract_floor_image(pts_2d)
        if floor_img is not None:
            print("Floor image:", floor_img.shape)

        print("\n=== Step 4: Detect Track ===")
        track_2d = detector.detect(floor_img, origin, scale)
        if track_2d is not None:
            # Convert 2D track back to 3D on floor plane
            center = floor_pts.mean(axis=0)
            up = normal / np.linalg.norm(normal)
            if abs(up[2]) > 0.9:
                right = np.cross(up, np.array([1, 0, 0]))
            else:
                right = np.cross(up, np.array([0, 0, 1]))
            right = right / np.linalg.norm(right)
            forward = np.cross(right, up)
            forward = forward / np.linalg.norm(forward)
            transform_mat = np.array([right, forward, up]).T
            track_3d = (track_2d @ transform_mat.T) + center
    else:
        print("Usage: python main_scan.py --scan path/to/scan.obj")
        print("   or: python main_scan.py --demo")
        return

    if view_only or demo:
        print("\n=== Step 5: Launch 3D Viewer ===")
        try:
            from scanner.scan_viewer import ScanViewer
            viewer = ScanViewer(title="3D Scan - STM32 Digital Twin")
            viewer.set_mesh(vertices, faces)
            viewer.set_track(track_3d)
            if track_3d is not None and len(track_3d) > 0:
                viewer.set_car(track_3d[0, 0], track_3d[0, 1], track_3d[0, 2], 0)
            viewer.run()
        except Exception as e:
            print("3D viewer failed:", e)
            print("Falling back to 2D visualization...")
            _fallback_2d(track_3d, vertices)
    else:
        print("\nPipeline complete!")
        if track_3d is not None:
            print("Track points:", len(track_3d))


def _fallback_2d(track_3d, vertices):
    """Fallback 2D visualization using OpenCV."""
    if track_3d is None:
        print("No track to display")
        return

    xy = track_3d[:, :2]
    xy_min = xy.min(axis=0)
    xy_max = xy.max(axis=0)
    extent = xy_max - xy_min
    scale = 600 / max(extent.max(), 0.1)
    offset = np.array([50, 50])

    img = np.ones((700, 700, 3), dtype=np.uint8) * 40

    # Draw floor points if available
    if vertices is not None and len(vertices) > 0:
        vxy = vertices[:, :2]
        vpx = ((vxy - xy_min) * scale + offset).astype(int)
        mask = (vpx[:, 0] >= 0) & (vpx[:, 0] < 700) & (vpx[:, 1] >= 0) & (vpx[:, 1] < 700)
        for p in vpx[mask]:
            img[p[1], p[0]] = (60, 65, 70)

    # Draw track
    pts = ((xy - xy_min) * scale + offset).astype(np.int32)
    for i in range(len(pts) - 1):
        cv2.line(img, tuple(pts[i]), tuple(pts[i + 1]), (0, 180, 255), 3)

    # Draw start point
    cv2.circle(img, tuple(pts[0]), 8, (0, 255, 0), -1)
    cv2.putText(img, "START", (pts[0][0] + 10, pts[0][1]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.putText(img, "Track detected: %d points" % len(pts),
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(img, "Press any key to close",
                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

    cv2.imshow("Detected Track (2D)", img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="3D Scan -> STM32 Digital Twin Pipeline")
    parser.add_argument("--scan", type=str, default=None,
                        help="Path to 3D scan file (OBJ/PLY/GLB)")
    parser.add_argument("--demo", action="store_true",
                        help="Run with generated demo scan")
    parser.add_argument("--view-only", action="store_true",
                        help="Only view the scan (no simulation)")
    args = parser.parse_args()

    run_pipeline(scan_path=args.scan, demo=args.demo,
                 view_only=args.view_only)
