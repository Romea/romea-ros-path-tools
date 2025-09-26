import fields2cover as f2c
import pymap3d as pm
import json

from romea_path_tools.path_planning_utils import discretize_swaths
from romea_path_tools.path import Path


class PathGenerator:
    def __init__(self, robot_width, operation_width, min_radius):
        self.swaths = None
        self.path = None
        self.polygon = None
        self.origin = (0, 0, 0)

        self.robot = f2c.Robot(robot_width, operation_width)
        self.robot.setMinTurningRadius(min_radius)
        self.robot.setCruiseVel(1.0)
        self.robot.setMaxDiffCurv(0.4)  # 1/m²
        self.step_size = 0.1  # m

    def create_swaths_from_points(self, points):
        self.swaths = f2c.Swaths()
        for a, b in zip(points[::2], points[1::2]):
            line_string = f2c.LineString(
                f2c.Point(*a),
                f2c.Point(*b),
            )
            swath = f2c.Swath(line_string)
            self.swaths.emplace_back(swath)

    def create_swaths_from_csv(self, filename):
        points = []
        with open(filename, "r") as file:
            file.readline()
            for line in file.readlines():
                values = tuple(map(float, line.split(",")))
                points.append(values)
        self.create_swaths_from_points(points)

    def create_swaths_from_geojson(self, filename):
        with open(filename, "r") as file:
            data = json.load(file)

        coords = []
        for feature in data["features"]:
            type = feature["geometry"]["type"]
            geo_coords = feature["geometry"]["coordinates"]
            if type in ("LineString", "MultiPoint"):
                coords.extend(geo_coords)
            elif type == "Point":
                coords.append(geo_coords)
            elif type == "MultiLineString":
                for group in geo_coords:
                    coords.extend(group)

        is_first_point = True
        points = []
        for geo_point in coords:
            if len(geo_point) == 3:
                lon, lat, alt = geo_point
            else:
                lon, lat = geo_point
                alt = 0.0

            if is_first_point:
                self.origin = lon, lat, alt
                is_first_point = False

            x, y, _ = pm.geodetic2enu(
                lat, lon, alt, self.origin[1], self.origin[0], self.origin[2]
            )
            points.append((x, y))
        self.create_swaths_from_points(points)

    def path_planning(self):
        path_planner = f2c.PP_PathPlanning()

        # turning = f2c.PP_DubinsCurves()
        turning = f2c.PP_DubinsCurvesCC()
        # turning = f2c.PP_ReedsSheppCurves()
        # turning = f2c.PP_ReedsSheppCurvesHC()

        turning.discretization = self.step_size
        self.path = path_planner.planPath(self.robot, self.swaths, turning)

        # fix: Add missing last point manually
        if self.swaths.size():
            last_state = f2c.PathState()
            last_state.point = self.swaths.back().endPoint()
            self.path.addState(last_state)

        self.path = discretize_swaths(self.path, self.step_size + 0.01)

    def get_tiara_path(self):
        tiara_path = Path()
        tiara_path.columns = ["x", "y", "speed"]

        tiara_path.anchor = self.origin[1], self.origin[0], self.origin[2]

        TURN = f2c.PathSectionType_TURN
        SWATH = f2c.PathSectionType_SWATH
        previous_dir = None
        previous_type = TURN

        for i, state in enumerate(self.path.getStates()):
            if previous_dir != state.dir:
                tiara_path.append_section([])

            if previous_type == SWATH and state.type == TURN:
                if i > 0:
                    tiara_path.append_annotation("zone_exit", "work", i - 1)
                tiara_path.append_annotation("zone_enter", "uturn", i)

            if previous_type == TURN and state.type == SWATH:
                if i > 0:
                    tiara_path.append_annotation("zone_exit", "uturn", i - 1)
                tiara_path.append_annotation("zone_enter", "work", i)

            state.velocity *= state.dir
            tiara_path.append_point((state.point.getX(), state.point.getY(), state.velocity))

            previous_dir = state.dir
            previous_type = state.type

        tiara_path.append_annotation("zone_exit", "work", len(self.path.getStates()) - 1)
        return tiara_path

    def export_path(self, filename):
        tiara_path = self.get_tiara_path()
        tiara_path.save(filename)
