#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate a printable AprilTag marker image for the car roof."""

from __future__ import print_function

import argparse
import os
import sys

import cv2
import numpy as np


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate an AprilTag 36h11 marker PNG")
    parser.add_argument("--id", type=int, default=0)
    parser.add_argument("--pixels", type=int, default=1000)
    parser.add_argument("--margin", type=int, default=120)
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv or sys.argv[1:])
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    marker = cv2.aruco.generateImageMarker(dictionary, args.id, args.pixels)
    canvas = np.full((args.pixels + args.margin * 2, args.pixels + args.margin * 2), 255, dtype=np.uint8)
    canvas[args.margin:args.margin + args.pixels, args.margin:args.margin + args.pixels] = marker
    output = os.path.abspath(args.output or os.path.join(os.path.dirname(__file__), "apriltag_36h11_id%d.png" % args.id))
    encoded_ok, encoded = cv2.imencode(".png", canvas)
    if not encoded_ok:
        raise RuntimeError("failed to write %s" % output)
    encoded.tofile(output)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
