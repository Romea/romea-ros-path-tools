import operator
import os
import math
import json
import warnings
import numpy as np
from pymap3d import enu
import geojson as gj
import fields2cover as f2c

from .romea_path import RomeaPath
from . import kml


class ParseError(RuntimeError):
    pass


class Path:

    def __init__(self):
        self.anchor = (0, 0, 0)
        self.columns = None
        self.points = []
        self.sections = []
        self.annotations = []
        self.punctuals = []
        self.row_zones = []
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

        if 'points' not in data:
            raise ParseError("the element 'points' is required in a trajectory file")
        else:
            points = data['points']

        path.columns = []
        for segment in points:
            for col in segment['columns']:
                if col != 'punctual' and col not in path.columns:
                    path.columns.append(col)

        all_seg_cols = [[c for c in seg['columns'] if c != 'punctual'] for seg in points]
        if any(cols != all_seg_cols[0] for cols in all_seg_cols[1:]):
            warnings.warn(
                "segments have mixed columns; missing values filled with NaN and will be omitted on export",
                UserWarning, stacklevel=2,
            )

        for segment in points:
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
                raise ParseError(
                    "cannot import a v4 trajectory containing 'turn_segment' entries: "
                    "turn geometry must be pre-computed (use 'turn_path' instead)"
                )

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

    def save_v4(self, filename, curve_type=None, include_turn_geometry=False, robot_config=None):
        """Save the path in version 4 of the JSON format used by romea_path"""
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
                        if curve_type:
                            seg['turn_type'] = curve_type
                        segments.append(seg)

                segments.append(
                    {
                        'segment_type': 'row_line',
                        'columns': ['x', 'y'],
                        'values': [row_start_xy, row_end_xy],
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
