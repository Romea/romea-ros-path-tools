import operator
import os
import json
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
        path.anchor = (anchor_coord['lon'], anchor_coord['lat'], anchor_coord['alt'])

        if 'points' not in data:
            raise ParseError("the element 'points' is required in a trajectory file")
        else:
            points = data['points']

        for segment in points:
            segment_type = segment['segment_type']
            if not path.columns:
                path.columns = [c for c in segment['columns'] if c != 'punctual']

            if segment_type == 'row_path':
                if segment['columns'][-1] == 'punctual':
                    vals = [v[:-1] for v in segment['values']]
                else:
                    vals = segment['values']
                row_start = len(path.points)
                path.points.extend(vals)
                path.row_zones.append((row_start, len(path.points) - 1))

            if segment_type == 'row_line':
                row_start = len(path.points)
                path.append_annotation("zone_enter", "work", row_start)
                ind_x = segment['columns'].index('x')
                ind_y = segment['columns'].index('y')
                step = 0.1

                p1 = np.array([segment['values'][0][ind_x], segment['values'][0][ind_y]])
                p2 = np.array([segment['values'][-1][ind_x], segment['values'][-1][ind_y]])

                # distance along the segment
                length = np.linalg.norm(p2 - p1)
                n_steps = int(length / step)

                coords = [p1 + (p2 - p1) * t for t in np.linspace(0, 1, n_steps + 1)]
                vals = []
                for c in coords:
                    value = segment['values'][0].copy()
                    value[ind_x] = c[0]
                    value[ind_y] = c[1]
                    vals.append(value)
                path.points.extend(vals)
                path.row_zones.append((row_start, len(path.points) - 1))
                path.append_annotation("zone_exit", "work", len(path.points) - 1)

            if segment_type == 'turn_segment':
                path.append_annotation("zone_enter", "uturn", len(path.points))
                ind_x = segment['columns'].index('x')
                ind_y = segment['columns'].index('y')
                for v in segment['values']:
                    path.append_point([v[ind_x], v[ind_y]])
                path.append_annotation("zone_exit", "uturn", len(path.points) - 1)

            if segment_type == 'turn_path':
                path.append_annotation("zone_enter", "uturn", len(path.points))
                if segment['columns'][-1] == 'punctual':
                    vals = [v[:-1] for v in segment['values']]
                else:
                    vals = segment['values']

                ind_x = segment['columns'].index('x')
                ind_y = segment['columns'].index('y')

                points = np.array(vals)[:, [ind_x, ind_y]]
                sections_indices = []
                for i, (prec, curr, next) in enumerate(zip(points[:-2], points[1:-1], points[2:])):
                    if not path.same_direction(prec, curr, next):
                        sections_indices.append(i + 1)

                n_points = len(path.points)
                sections_indices = [i + n_points for i in sections_indices]
                path.points.extend(vals)
                path.create_sections(sections_indices)
                path.append_annotation("zone_exit", "uturn", len(path.points) - 1)

        return path

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

    def save(self, filename):
        """Save the in the JSON format used by romea_path"""
        data = {
            'version': '2',
            'origin': {
                'type': 'WGS84',
                'coordinates': self.anchor,
            },
            'points': {
                'columns': self.columns,
                'values': self.points,
            },
            'sections': self.section_indexes(),
            'annotations': self.annotations,
        }

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

    def save_v4(self, filename, curve_type=None, include_turn_geometry=False, robot_config=None):
        if not self.row_zones:
            raise ValueError(
                "Path has no row_zones; save_v4 requires the path to have been built "
                "with swath structure (e.g. via get_tiara_path() or loaded from a v4 file)"
            )

        data = {
            'version': '4',
            'file_type': 'mission_order',
            'origin': {
                'type': 'WGS84',
                'coordinates': {
                    'lat': self.anchor[1],
                    'lon': self.anchor[0],
                    'alt': self.anchor[2],
                },
            },
        }
        if robot_config:
            data['robot'] = robot_config

        x_idx = self.columns.index('x')
        y_idx = self.columns.index('y')
        segments = []
        prev_end = -1

        for row_start, row_end in sorted(self.row_zones, key=lambda z: z[0]):
            turn_start = prev_end + 1
            turn_end = row_start - 1
            if turn_start <= turn_end:
                if include_turn_geometry:
                    segments.append({
                        'segment_type': 'turn_path',
                        'columns': self.columns,
                        'values': self.points[turn_start:turn_end + 1],
                    })
                else:
                    seg = {
                        'segment_type': 'turn_segment',
                        'columns': ['x', 'y'],
                        'values': [
                            [self.points[turn_start][x_idx], self.points[turn_start][y_idx]],
                            [self.points[turn_end][x_idx],   self.points[turn_end][y_idx]],
                        ],
                    }
                    if curve_type:
                        seg['turn_type'] = curve_type
                    segments.append(seg)

            segments.append({
                'segment_type': 'row_line',
                'columns': ['x', 'y'],
                'values': [
                    [self.points[row_start][x_idx], self.points[row_start][y_idx]],
                    [self.points[row_end][x_idx],   self.points[row_end][y_idx]],
                ],
            })
            prev_end = row_end

        data['points'] = segments
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

    def save_csv(self, filename):
        """Save the path in CSV format. The point are expressed in 'x' and 'y' coordinates"""
        with open(filename, 'w') as f:
            f.write(','.join(self.columns) + '\n')

            for point in self.points:
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
        indexes = []
        for i, key in enumerate(self.columns):
            if key not in ['x', 'y']:
                indexes.append(i)

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

    @staticmethod
    def same_direction(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> bool:
        return np.dot(p2 - p1, p3 - p2) > 0

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
