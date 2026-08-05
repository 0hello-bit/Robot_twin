import math


def wrap_degrees(angle):
    return (float(angle) + 180.0) % 360.0 - 180.0


def smooth_angle(previous, current, alpha):
    delta = wrap_degrees(float(current) - float(previous))
    return wrap_degrees(float(previous) + delta * float(alpha))


def solve_linear(matrix, values):
    size = len(values)
    augmented = [list(map(float, matrix[row])) + [float(values[row])] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("singular calibration points")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][index] - factor * augmented[column][index]
                for index in range(size + 1)
            ]
    return [augmented[row][-1] for row in range(size)]


def homography_from_four_points(image_points, world_points):
    if len(image_points) != 4 or len(world_points) != 4:
        raise ValueError("four image and four world points are required")
    matrix = []
    values = []
    for (u_value, v_value), (x_value, z_value) in zip(image_points, world_points):
        u_value = float(u_value)
        v_value = float(v_value)
        x_value = float(x_value)
        z_value = float(z_value)
        matrix.append([u_value, v_value, 1.0, 0.0, 0.0, 0.0, -x_value * u_value, -x_value * v_value])
        values.append(x_value)
        matrix.append([0.0, 0.0, 0.0, u_value, v_value, 1.0, -z_value * u_value, -z_value * v_value])
        values.append(z_value)
    solution = solve_linear(matrix, values)
    return [
        solution[0:3],
        solution[3:6],
        [solution[6], solution[7], 1.0],
    ]


def project_point(homography, u_value, v_value):
    denominator = homography[2][0] * u_value + homography[2][1] * v_value + homography[2][2]
    if abs(denominator) < 1e-12:
        raise ValueError("point projects to infinity")
    x_value = (homography[0][0] * u_value + homography[0][1] * v_value + homography[0][2]) / denominator
    z_value = (homography[1][0] * u_value + homography[1][1] * v_value + homography[1][2]) / denominator
    return float(x_value), float(z_value)


def polygon_area(corners):
    area = 0.0
    for index in range(len(corners)):
        x1, y1 = corners[index]
        x2, y2 = corners[(index + 1) % len(corners)]
        area += float(x1) * float(y2) - float(x2) * float(y1)
    return abs(area) * 0.5


def pose_from_corners(corners, homography, front_edge="top", yaw_offset_deg=0.0):
    world = [project_point(homography, point[0], point[1]) for point in corners]
    center_x = sum(point[0] for point in world) / 4.0
    center_z = sum(point[1] for point in world) / 4.0
    edge_indices = {
        "top": (0, 1),
        "right": (1, 2),
        "bottom": (2, 3),
        "left": (3, 0),
    }
    first, second = edge_indices.get(front_edge, (0, 1))
    front_x = (world[first][0] + world[second][0]) * 0.5
    front_z = (world[first][1] + world[second][1]) * 0.5
    yaw = math.degrees(math.atan2(-(front_z - center_z), front_x - center_x))
    return {
        "x": center_x,
        "z": center_z,
        "yaw_deg": wrap_degrees(yaw + float(yaw_offset_deg)),
        "pixel_area": polygon_area(corners),
    }


class PoseFilter(object):
    def __init__(self, position_alpha, yaw_alpha, max_jump):
        self.position_alpha = float(position_alpha)
        self.yaw_alpha = float(yaw_alpha)
        self.max_jump = float(max_jump)
        self.value = None

    def reset(self):
        self.value = None

    def update(self, pose):
        if self.value is None:
            self.value = dict(pose)
            return dict(self.value)
        previous = self.value
        jump = math.sqrt((pose["x"] - previous["x"]) ** 2 + (pose["z"] - previous["z"]) ** 2)
        if self.max_jump > 0 and jump > self.max_jump:
            return None
        self.value = dict(pose)
        self.value["x"] = previous["x"] * (1.0 - self.position_alpha) + pose["x"] * self.position_alpha
        self.value["z"] = previous["z"] * (1.0 - self.position_alpha) + pose["z"] * self.position_alpha
        self.value["yaw_deg"] = smooth_angle(previous["yaw_deg"], pose["yaw_deg"], self.yaw_alpha)
        return dict(self.value)

