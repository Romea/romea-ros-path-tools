import operator
import os
import math
import json
import warnings
from enum import Enum
import numpy as np
from pymap3d import enu
import geojson as gj
import fields2cover as f2c

from .romea_path import RomeaPath
from . import kml


class ParseError(RuntimeError):
    pass


class TurnPlanner(Enum):
    Dubins = f2c.PP_DubinsCurves
    DubinsCC = f2c.PP_DubinsCurvesCC
    Reeds_Shepp = f2c.PP_ReedsSheppCurves
    Reeds_SheppHC = f2c.PP_ReedsSheppCurvesHC


class Path:

    def __init__(self):
        self.anchor = (0, 0, 0)
        self.columns = None
        self.points = []
        self.sections = []
        self.annotations = []
        self.punctuals = []
        self.row_zones = []
        self.turn_zones = []
        self.robot = None
        self.name = None

    @staticmethod
    def load(filename):
        """Read the file extension and build a path from the correct format"""
        if filename.endswith('.txt'):
            return Path.from_romea(filename)
        elif filename.endswith('.traj'):
            return Path.from_tiara(filename)
        elif filename.endswith('.kml'):
            return Path.from_kml(filename)
        elif filename.endswith('.wgs84.csv'):
            return Path.from_wgs84_csv(filename)
        elif filename.endswith('.csv'):
            return Path.from_csv(filename)
        elif filename.endswith('.geojson'):
            return Path.from_geojson(filename)
        else:
            raise RuntimeError(f"unsupported file format for input file '{filename}'")

    @staticmethod
    def from_tiara(filename):
        with open(filename, 'r') as f:
            data = json.load(f)
        version = data['version']

        if version == '2':
            return Path.from_tiara_v2(data, filename)
        elif version == '4':
            return Path.from_tiara_v4(data, filename)
        else:
            raise RuntimeError(f"unsupported version for tiara input file '{filename}'")

    @staticmethod
    def from_tiara_v4(data, filename):
        origin = data['origin']

        path = Path()
        path.name = os.path.basename(filename)
        if origin['type'] != 'WGS84':
            raise ParseError(f"unknown origin type '{origin['type']}'; only 'WGS84' is accepted")
        anchor_coord = origin['coordinates']
        path.anchor = (anchor_coord['lat'], anchor_coord['lon'], anchor_coord['alt'])
        path.robot = data.get('robot')

        if 'points' not in data:
            raise ParseError("the element 'points' is required in a trajectory file")
        else:
            segments = data['points']

        path.columns = []
        for segment in segments:
            for col in segment['columns']:
                if col != 'punctual' and col not in path.columns:
                    path.columns.append(col)

        for i, segment in enumerate(segments):
            segment_type = segment['segment_type']
            vals, puncts = Path._remap_segment_values(segment, path.columns)

            if segment_type == 'row_path':
                row_start = len(path.points)
                if not path.sections:
                    path.sections.append([])
                path.sections[-1].extend(vals)
                path.points.extend(vals)
                path.punctuals.extend(puncts)
                path.row_zones.append((row_start, len(path.points) - 1))

            if segment_type == 'row_line':
                row_start = len(path.points)
                path.append_annotation("zone_enter", "work", row_start)
                ind_x = path.columns.index('x')
                ind_y = path.columns.index('y')
                step = 0.1

                p1 = np.array([vals[0][ind_x], vals[0][ind_y]])
                p2 = np.array([vals[-1][ind_x], vals[-1][ind_y]])

                length = np.linalg.norm(p2 - p1)
                n_steps = int(length / step)

                first_value = vals[0]
                coords = [p1 + (p2 - p1) * t for t in np.linspace(0, 1, n_steps + 1)]
                interp_puncts = [{} for _ in coords]
                interp_puncts[0] = puncts[0]
                interp_puncts[-1] = puncts[-1]
                vals = []
                for c in coords:
                    value = first_value.copy()
                    value[ind_x] = c[0]
                    value[ind_y] = c[1]
                    vals.append(value)
                if not path.sections:
                    path.sections.append([])
                path.sections[-1].extend(vals)
                path.points.extend(vals)
                path.punctuals.extend(interp_puncts)
                path.row_zones.append((row_start, len(path.points) - 1))
                path.append_annotation("zone_exit", "work", len(path.points) - 1)

            if segment_type == 'turn_segment':
                if not path.robot:
                    raise ParseError(
                        "cannot import a 'turn_segment' without a 'robot' block in the file"
                    )
                robot = Path._make_f2c_robot(path.robot)
                start_angle = Path._adjacent_row_angle(segments, i, 'prev')
                end_angle = Path._adjacent_row_angle(segments, i, 'next')
                turn_type = segment.get('turn_type')
                turn_vals, turn_puncts, dir_breaks = Path._compute_turn_geometry(
                    segment, robot, start_angle, end_angle, path.columns
                )

                turn_start = len(path.points)
                path.append_annotation("zone_enter", "uturn", turn_start)

                n_points = len(path.points)
                path.points.extend(turn_vals)
                path.punctuals.extend(turn_puncts)
                if dir_breaks:
                    path.create_sections([n_points] + [n_points + k for k in dir_breaks])
                else:
                    if not path.sections:
                        path.sections.append([])
                    path.sections[-1].extend(turn_vals)

                path.append_annotation("zone_exit", "uturn", len(path.points) - 1)
                path.turn_zones.append((turn_start, len(path.points) - 1, turn_type))

            if segment_type == 'turn_path':
                path.append_annotation("zone_enter", "uturn", len(path.points))

                sections_indices = []
                if 'speed' in path.columns:
                    ind_speed = path.columns.index('speed')
                    for i in range(1, len(vals)):
                        prev, curr = vals[i - 1][ind_speed], vals[i][ind_speed]
                        if not (math.isnan(prev) or math.isnan(curr)) and prev * curr < 0:
                            sections_indices.append(i)

                n_points = len(path.points)
                path.points.extend(vals)
                path.punctuals.extend(puncts)
                if sections_indices:
                    path.create_sections([n_points] + [n_points + i for i in sections_indices])
                else:
                    if not path.sections:
                        path.sections.append([])
                    path.sections[-1].extend(vals)
                path.append_annotation("zone_exit", "uturn", len(path.points) - 1)

        return path

    @staticmethod
    def _remap_segment_values(segment, unified_columns):
        """Remap the values of a v4 segment to the unified column order.
        Columns absent from the segment are filled with NaN.
        Return (values, punctuals) where punctuals contains one dict per point
        ({} when the segment has no 'punctual' column).
        """
        seg_cols = segment['columns']
        indices = {c: i for i, c in enumerate(seg_cols) if c != 'punctual'}
        punct_index = seg_cols.index('punctual') if 'punctual' in seg_cols else None
        values = [
            [row[indices[col]] if col in indices else float('nan') for col in unified_columns]
            for row in segment['values']
        ]
        punctuals = [
            row[punct_index] if punct_index is not None else {} for row in segment['values']
        ]
        return values, punctuals

    @staticmethod
    def _make_f2c_robot(robot_config):
        robot = f2c.Robot(robot_config.get('width', 1.0), robot_config.get('tool_width', 1.0))
        robot.setMinTurningRadius(robot_config.get('min_curve_radius', 2.5))
        if 'max_diff_curve' in robot_config:
            robot.setMaxDiffCurv(robot_config['max_diff_curve'])
        robot.setCruiseVel(1.0)
        return robot

    @staticmethod
    def _adjacent_row_angle(segments, turn_idx, direction):
        """Return the heading of the row_line/row_path adjacent to segments[turn_idx].

        direction='prev': scan backward, return the heading of the preceding row.
        direction='next': scan forward, return the heading of the following row.
        Raises ParseError if no adjacent row segment is found (malformed file).
        """
        step = -1 if direction == 'prev' else 1
        for j in range(turn_idx + step, -1 if step < 0 else len(segments), step):
            seg = segments[j]
            if seg['segment_type'] in ('row_line', 'row_path'):
                cols = seg['columns']
                xi, yi = cols.index('x'), cols.index('y')
                p1, p2 = seg['values'][0], seg['values'][-1]
                return math.atan2(p2[yi] - p1[yi], p2[xi] - p1[xi])
        raise ParseError(
            f"turn_segment at index {turn_idx} has no adjacent row segment "
            f"({'before' if direction == 'prev' else 'after'} it); "
            "a turn_segment must always be between two row segments"
        )

    @staticmethod
    def _compute_turn_geometry(segment, robot, start_angle, end_angle, unified_columns):
        """Call the F2C path planner for a turn_segment and return
        (vals, punctuals, dir_break_indices).

        dir_break_indices lists the indices in vals where the robot reverses direction,
        which the caller uses to split sections.
        """
        turn_type = segment.get('turn_type')
        if turn_type is None:
            raise ParseError("turn_segment is missing the required 'turn_type' field")
        try:
            planner = TurnPlanner[turn_type].value()
        except KeyError:
            raise ParseError(
                f"unknown turn_type '{turn_type}'; "
                f"expected one of: {', '.join(p.name for p in TurnPlanner)}"
            )

        seg_cols = segment['columns']
        xi, yi = seg_cols.index('x'), seg_cols.index('y')
        si = seg_cols.index('speed') if 'speed' in seg_cols else None
        raw = segment['values']
        speed = abs(raw[0][si]) if si is not None else 1.0
        robot.setCruiseVel(speed)

        start_pt = f2c.Point(raw[0][xi], raw[0][yi])
        end_pt = f2c.Point(raw[-1][xi], raw[-1][yi])
        f2c_path = planner.createTurn(robot, start_pt, start_angle, end_pt, end_angle)

        x_col = unified_columns.index('x')
        y_col = unified_columns.index('y')
        spd_col = unified_columns.index('speed') if 'speed' in unified_columns else None

        vals = []
        dir_break_indices = []
        prev_dir = None
        for state in f2c_path.getStates():
            if prev_dir is not None and state.dir != prev_dir:
                dir_break_indices.append(len(vals))
            prev_dir = state.dir
            row = [float('nan')] * len(unified_columns)
            row[x_col] = state.point.getX()
            row[y_col] = state.point.getY()
            if spd_col is not None:
                row[spd_col] = state.velocity * state.dir
            vals.append(row)

        punctuals = [{} for _ in vals]
        return vals, punctuals, dir_break_indices

    def _find_turn_zone(self, start_idx):
        """Return the turn_zone tuple whose start index matches start_idx, or None."""
        for tz in self.turn_zones:
            if tz[0] == start_idx:
                return tz
        return None

    @staticmethod
    def from_tiara_v2(data, filename):
        origin = data['origin']

        path = Path()
        path.name = os.path.basename(filename)
        if origin['type'] != 'WGS84':
            raise ParseError(f"unknown origin type '{origin['type']}'; only 'WGS84' is accepted")
        path.anchor = origin['coordinates']

        if 'points' not in data:
            raise ParseError("the element 'points' is required in a trajectory file")
        else:
            path.columns = data['points']['columns']
            path.points = data['points']['values']

        if 'annotations' in data:
            path.annotations = data['annotations']

        if 'sections' not in data:
            path.sections = path.points
        else:
            path.create_sections(data['sections'])

        return path

    @staticmethod
    def from_romea(filename):
        """Build a path from a file in the old romea format ('.txt')"""
        old_path = RomeaPath.load(filename)
        path = Path()
        path.name = os.path.basename(filename)
        path.columns = ['x', 'y', 'speed']
        path.anchor = old_path.anchor

        for old_section in old_path.sections:
            section = []
            for old_point in old_section:
                point = [old_point.x, old_point.y, old_point.speed]
                path.points.append(point)
                section.append(point)
            path.sections.append(section)

        return path

    @staticmethod
    def from_kml(filename):
        """Build a path from a KML file that contains a linestring ('.kml')"""
        linestring = kml.parse_polygon(filename)
        path = Path()
        path.name = os.path.basename(filename)
        orig = linestring.origin
        path.anchor = (orig[1], orig[0], orig[2])
        path.columns = ['x', 'y']
        for point in linestring.points:
            path.append_point([point[0], point[1]])

        return path

    @staticmethod
    def from_wgs84_csv(filename):
        """Build a path from a CSV file containing latitude, longitude and altitude
        ('.wgs84.csv'). The column separator must be ','.
        """
        file = open(filename, 'r')
        path = Path()
        path.name = os.path.basename(filename)

        # read headers
        file.readline()

        # read first line to get the anchor
        path.anchor = tuple(map(float, file.readline().split(',')))
        path.append_point([0, 0, 0])

        for line in file.readlines():
            geo_coords = tuple(map(float, line.split(',')))
            point = enu.geodetic2enu(*geo_coords, *path.anchor)
            path.append_point([point[0], point[1]])

        return path

    @staticmethod
    def from_csv(filename):
        """Build a path from a CSV file containing 'x', 'y' and other columns
        ('.csv'). The column separator must be ','.
        """
        file = open(filename, 'r')
        path = Path()
        path.name = os.path.basename(filename)

        # read headers
        path.columns = file.readline().split(',')

        for line in file.readlines():
            point = list(map(float, line.split(',')))
            path.append_point(point)

        return path

    @staticmethod
    def from_geojson(filename):
        """Build a path from a GeoJSON file that contains a Point (anchor)
        and a MultiLineString (traj) ('.geojson').
        Currently, extra columns are not supported
        """
        path = Path()
        path.name = os.path.basename(filename)

        with open(filename, 'r') as f:
            data = json.load(f)

        for feature in data['features']:
            if feature['id'] == 'origin':
                coords = feature['geometry']['coordinates']
                path.anchor = coords[1], coords[0], coords[2]

            elif feature['id'] == 'sections':
                coords = feature['geometry']['coordinates']
                for section in coords:
                    path.append_section([])
                    for geo_pt in section:
                        point = enu.geodetic2enu(geo_pt[1], geo_pt[0], geo_pt[2], *path.anchor)
                        path.append_point([point[0], point[1]])

                path.annotations = feature['annotations']

        return path

    def positions(self):
        """return an numpy array of (x, y) for each point"""
        pts = np.array(self.points)
        x_index = self.columns.index('x')
        y_index = self.columns.index('y')
        return pts[:, [x_index, y_index]]

    def section_indexes(self):
        """Return the list of point indexes that correspond to the begining of a new section"""
        indexes = []
        index = 0
        for section in self.sections:
            indexes.append(index)
            index += len(section)
        return indexes

    def create_sections(self, indexes):
        """Fill the 'sections' attribute with the points of the path according
        to the section indexes.
        """
        if indexes and indexes[-1] != len(self.points):
            indexes = indexes + [len(self.points)]

        for begin, end in zip(indexes[:-1], indexes[1:]):
            self.sections.append(self.points[begin:end])

    @staticmethod
    def _is_nan(value):
        return isinstance(value, float) and math.isnan(value)

    @staticmethod
    def _drop_nan_columns(columns, values):
        """Return (columns, values) without the columns containing at least one NaN"""
        keep = [i for i in range(len(columns)) if not any(Path._is_nan(row[i]) for row in values)]
        if len(keep) == len(columns):
            return columns, values
        return [columns[i] for i in keep], [[row[i] for i in keep] for row in values]

    def _nan_free_points(self):
        """Return (columns, points) of the whole path without the columns that
        contain NaN values (columns missing in some segments of the source file),
        warning about what was dropped.
        """
        columns, values = Path._drop_nan_columns(self.columns, self.points)
        if len(columns) != len(self.columns):
            dropped = [c for c in self.columns if c not in columns]
            warnings.warn(
                f"columns {dropped} are missing in some segments (NaN values) "
                "and were dropped from the export",
                UserWarning,
                stacklevel=3,
            )
        return columns, values

    def save(self, filename):
        """Save the path in the JSON format used by romea_path"""
        columns, values = self._nan_free_points()
        data = {
            'version': '2',
            'origin': {
                'type': 'WGS84',
                'coordinates': self.anchor,
            },
            'points': {
                'columns': columns,
                'values': values,
            },
            'sections': self.section_indexes(),
            'annotations': self.annotations,
        }

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

    def save_v4(self, filename, turning_type=None, include_turn_geometry=None, robot_config=None):
        """Save the path in version 4 of the JSON format used by romea_path"""
        if robot_config is None:
            robot_config = self.robot
        data = {
            'version': '4',
            'file_type': 'mission_order',
            'origin': {
                'type': 'WGS84',
                'coordinates': {
                    'lat': self.anchor[0],
                    'lon': self.anchor[1],
                    'alt': self.anchor[2],
                },
            },
        }
        if robot_config:
            data['robot'] = robot_config

        if not self.row_zones:
            data['points'] = [self._turn_path_segment(0, len(self.points) - 1)]
        else:
            x_idx = self.columns.index('x')
            y_idx = self.columns.index('y')
            segments = []
            prev_end = -1
            prev_row_end_xy = None

            for zone in sorted(self.row_zones, key=lambda z: z[0]):
                row_start = zone[0]
                row_end = zone[1]
                if len(zone) >= 4:
                    row_start_xy = list(zone[2])
                    row_end_xy = list(zone[3])
                else:
                    row_start_xy = [self.points[row_start][x_idx], self.points[row_start][y_idx]]
                    row_end_xy = [self.points[row_end][x_idx], self.points[row_end][y_idx]]

                turn_start = prev_end + 1
                turn_end = row_start - 1
                if turn_start <= turn_end:
                    if include_turn_geometry:
                        segments.append(self._turn_path_segment(turn_start, turn_end))
                    else:
                        t_start_xy = (
                            prev_row_end_xy
                            if prev_row_end_xy is not None
                            else [self.points[turn_start][x_idx], self.points[turn_start][y_idx]]
                        )
                        seg = {
                            'segment_type': 'turn_segment',
                            'columns': ['x', 'y'],
                            'values': [t_start_xy, row_start_xy],
                        }
                        turn_zone = self._find_turn_zone(turn_start)
                        if turn_zone is not None:
                            seg['turn_type'] = turn_zone[2]
                        elif turning_type:
                            seg['turn_type'] = turning_type.name
                        segments.append(seg)

                segments.append(
                    {
                        'segment_type': 'row_line',
                        'columns': ['x', 'y', 'working_zone'],
                        'values': [row_start_xy + [1], row_end_xy + [1]],
                    }
                )
                prev_end = row_end
                prev_row_end_xy = row_end_xy

            data['points'] = segments

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

    def _point_punctuals(self, start, end):
        """Return the punctual dicts of the point range, or None if they are all empty"""
        puncts = [
            self.punctuals[i] if i < len(self.punctuals) else {} for i in range(start, end + 1)
        ]
        return puncts if any(puncts) else None

    @staticmethod
    def _append_punctual(segment, punctuals):
        """Append a 'punctual' column (kept last for readability) to a v4 segment"""
        if punctuals:
            segment['columns'] = list(segment['columns']) + ['punctual']
            segment['values'] = [
                list(row) + [punct] for row, punct in zip(segment['values'], punctuals)
            ]
        return segment

    def _turn_path_segment(self, start, end):
        columns, values = Path._drop_nan_columns(self.columns, self.points[start : end + 1])
        punctuals = self._point_punctuals(start, end)
        if 'speed' in columns or len(self.sections) <= 1:
            return Path._append_punctual(
                {
                    'segment_type': 'turn_path',
                    'columns': columns,
                    'values': values,
                },
                punctuals,
            )

        sec_starts = self.section_indexes()
        inner_transitions = [s for s in sec_starts if start < s <= end]

        if not inner_transitions:
            return Path._append_punctual(
                {
                    'segment_type': 'turn_path',
                    'columns': columns,
                    'values': values,
                },
                punctuals,
            )

        cols = list(columns) + ['speed']
        boundaries = [start] + inner_transitions + [end + 1]
        start_sec = sum(1 for s in sec_starts if s <= start) - 1
        speed_values = []
        for i, (seg_s, seg_e) in enumerate(zip(boundaries[:-1], boundaries[1:])):
            speed = 1.0 if (start_sec + i) % 2 == 0 else -1.0
            for pt in values[seg_s - start : seg_e - start]:
                speed_values.append(list(pt) + [speed])

        warnings.warn(
            "Path has multiple sections (direction changes) but no speed column. "
            "Arbitrary speed values (+1.0 / -1.0) have been added.",
            UserWarning,
            stacklevel=3,
        )
        return Path._append_punctual(
            {
                'segment_type': 'turn_path',
                'columns': cols,
                'values': speed_values,
            },
            punctuals,
        )

    def infer_row_zones_from_annotations(self):
        """Populate row_zones from zone_enter/exit work annotations (heuristic)"""
        self.row_zones = []
        enter_idx = None
        for ann in self.annotations:
            if ann['value'] != 'work':
                continue
            if ann['type'] == 'zone_enter':
                enter_idx = ann['point_index']
            elif ann['type'] == 'zone_exit' and enter_idx is not None:
                self.row_zones.append((enter_idx, ann['point_index']))
                enter_idx = None

    def save_csv(self, filename):
        """Save the path in CSV format. The point are expressed in 'x' and 'y' coordinates"""
        columns, values = self._nan_free_points()
        with open(filename, 'w') as f:
            f.write(','.join(columns) + '\n')

            for point in values:
                f.write(','.join(map(str, point)) + '\n')

    def save_wgs84_csv(self, filename):
        """Save the path in CSV format. The point are expressed in WGS84 coordinates"""
        with open(filename, 'w') as f:
            f.write(f'latitude,longitude,altitude\n')

            x_index = self.columns.index('x')
            y_index = self.columns.index('y')

            for p in self.points:
                lat, lon, alt = enu.enu2geodetic(p[x_index], p[y_index], 0, *self.anchor)
                f.write(f'{lat},{lon},{alt}\n')

    def save_kml(self, filename):
        """Save the path in KML format."""
        kml_data = kml.Kml()
        x_index = self.columns.index('x')
        y_index = self.columns.index('y')

        for p in self.points:
            lat, lon, alt = enu.enu2geodetic(p[x_index], p[y_index], 0, *self.anchor)
            kml_data.add_point(lon, lat, alt)

        kml_data.save(filename)

    def save_geojson(self, filename):
        """Save the path in GeoJSON format."""
        x_index = self.columns.index('x')
        y_index = self.columns.index('y')

        origin_point = [self.anchor[1], self.anchor[0], self.anchor[2]]
        origin = gj.Feature(id='origin', geometry=gj.Point(origin_point, precision=8))

        wgs84_sections = []
        for section in self.sections:
            wgs84_section = []
            for p in section:
                lat, lon, alt = enu.enu2geodetic(p[x_index], p[y_index], 0, *self.anchor)
                wgs84_section.append([lon, lat, alt])

            wgs84_sections.append(wgs84_section)

        extra = self.extra_columns()
        section_linestrings = gj.MultiLineString(wgs84_sections, precision=8)
        traj = gj.Feature(id='sections', geometry=section_linestrings, extra=extra)
        traj.update(annotations=self.annotations)

        features = gj.FeatureCollection([origin, traj])
        with open(filename, 'w') as f:
            gj.dump(features, f, indent=2)

    def extra_columns(self):
        """Return a dictionnary containing the columns that are not 'x' or 'y' and its values"""
        nan_free_columns, _ = self._nan_free_points()
        indexes = []
        for i, key in enumerate(self.columns):
            if key not in ['x', 'y'] and key in nan_free_columns:
                indexes.append(i)

        if not indexes:
            return {'columns': [], 'values': []}

        columns_select = operator.itemgetter(*indexes)
        columns = columns_select(self.columns)
        sections = []
        for section in self.sections:
            sections.append(list(map(columns_select, section)))

        return {'columns': columns, 'values': sections}

    def empty(self):
        """Return True if there is no points"""
        return len(self.points) == 0

    def append_section(self, section):
        """Add a section at the end of the path
        The points in this new section must respect the format of 'columns'
        """
        self.sections.append(section)
        self.points += section

    def append_point(self, point):
        """Add a point at the end of the last section of the path
        The point must respect the format of 'columns'
        """
        self.points.append(point)
        if not self.sections:
            self.sections.append([])
        self.sections[-1].append(point)

    def append_annotation(self, type, value, point_index):
        """Add an annotation to the path
        The annotations are ordered by point_index
        """
        new_annotation = {
            'type': type,
            'value': value,
            'point_index': point_index,
        }
        for i, annotation in enumerate(self.annotations):
            if point_index < annotation['point_index']:
                self.annotations.insert(i, new_annotation)
                return
        self.annotations.append(new_annotation)

    def next_zone(self, value, index):
        """Returns a tuple with the point_indices of the next annotations with types
        'zone_enter' and 'zone_exit' and 'point_index' > i
        """
        next_enter = None
        for annotation in self.annotations:
            if annotation['point_index'] < index or annotation['value'] != value:
                continue
            if annotation['type'] == 'zone_enter':
                next_enter = annotation['point_index']
            if next_enter is not None and annotation['type'] == 'zone_exit':
                return (next_enter, annotation['point_index'])

        return ()
