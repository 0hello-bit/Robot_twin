# CanMV K230 overhead tracker configuration.
# Edit these values after the exact board and camera installation are known.

PC_IP = "192.168.1.2"
PC_POSE_UDP_PORT = 8788

DETECT_WIDTH = 320
DETECT_HEIGHT = 240
TAG_ID = 0
TAG_FRONT_EDGE = "top"
TAG_YAW_OFFSET_DEG = 0.0
MINIMUM_PIXEL_AREA = 180.0

# The four calibration tags must be placed at:
# 10=(0,0), 11=(width,0), 12=(width,height), 13=(0,height)
CALIBRATION_TAG_IDS = (10, 11, 12, 13)
FLOOR_WIDTH = 2.0
FLOOR_HEIGHT = 1.5
CALIBRATION_FILE = "/sdcard/stm32_floor_calibration.json"

POSITION_ALPHA = 0.35
YAW_ALPHA = 0.30
MAX_JUMP = 0.35
SEND_INTERVAL_MS = 40
PREVIEW_TO_IDE = True

