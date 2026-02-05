import operator
import os
import json
import numpy as np
from pymap3d import enu
import geojson as gj

from .romea_path import RomeaPath
from . import kml


class ParseError(RuntimeError):
    pass


class Path:

    def __init__(self):
        self.anchor = (0, 0, 0)
        self.columns = ['x', 'y']
        self.points = []
        self.sections = []
        self.annotations = []
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
        path = Path()
        path.name = os.path.basename(filename)

        with open(filename, 'r') as f:
            data = json.load(f)

        origin = data['origin']
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

    def save_v4(self, filename):
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

        points = []
        segment = {}
        i = 0
        next_work_zone = self.next_zone('work', 0)
        new_segment = True
        while i < len(self.points):
            if next_work_zone and i >= next_work_zone[0]:
                if segment:
                    points.append(segment)
                segment = {
                    'segment_type': 'row_line',
                    'columns': self.columns,
                    'values': [self.points[i], self.points[next_work_zone[1]]],
                }
                points.append(segment)
                new_segment = True
                i = next_work_zone[1] + 1
                next_work_zone = self.next_zone('work', i)
            else:
                if new_segment:
                    segment = {
                        'segment_type': 'turn_path',
                        'columns': self.columns,
                        'values': [],
                    }
                    new_segment = False
                segment['values'].append(self.points[i])
                i += 1

        if not new_segment:
            points.append(segment)
        data['points'] = points

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
