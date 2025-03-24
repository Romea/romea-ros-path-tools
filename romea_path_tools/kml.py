import os
from dataclasses import dataclass
import xml.etree.ElementTree as ET
from pymap3d import enu

KML_HEADER_FORMAT = '''\
<?xml version="1.0" encoding="UTF-8"?> 
<kml xmlns="http://www.opengis.net/kml/2.2" 
     xmlns:gx="http://www.google.com/kml/ext/2.2" 
     xmlns:kml="http://www.opengis.net/kml/2.2"
     xmlns:atom="http://www.w3.org/2005/Atom"> 
  <Document> 
    <name>{}</name> 
    <Placemark> 
      <name>Trajectoire</name> 
      <LineString> 
        <tessellate>1</tessellate> 
        <coordinates> 
'''

KML_FOOTER = '''\
        </coordinates> 
      </LineString> 
    </Placemark> 
  </Document> 
</kml> 
'''


@dataclass
class GeoPoint:
    lon: float
    lat: float
    alt: float

    def __repr__(self):
        return f'{self.lon:.8f},{self.lat:.8f},{round(self.alt, 3)}'


class Kml:

    def __init__(self):
        self.points = []

    def add_point(self, lon, lat, alt=0):
        self.points.append(GeoPoint(lon, lat, alt))

    def save(self, filename):
        with open(filename, 'w') as file:
            file.write(KML_HEADER_FORMAT.format(os.path.basename(filename)))

            for point in self.points:
                file.write(f'{point}\n')

            file.write(KML_FOOTER)


class GeoPolygon:

    def __init__(self):
        self.geo_points = []
        self.points = []
        self.origin = None

    def add_geo_point(self, geo_point):
        ''' add WGS84 point and convert it to ENU if origin is defined '''
        self.geo_points.append(geo_point)

        if self.origin is not None:
            self._add_converted_point(geo_point)

    def _add_converted_point(self, geo_point):
        ''' convert WGS84 point and add it to points '''
        lon0, lat0, alt0 = tuple(self.origin)
        if len(geo_point) == 2:
            lon, lat = tuple(geo_point)
            alt = 0.
        else:
            lon, lat, alt = tuple(geo_point)
        point = enu.geodetic2enu(lat, lon, alt, lat0, lon0, alt0)
        self.points.append(point)

    def set_origin(self, origin):
        ''' set WGS84 origin point (correspond to [0, 0, 0] in ENU) '''
        if len(origin) == 2:
            self.origin = (*origin, 0.)
        else:
            self.origin = origin
        self.points.clear()

        for geo_point in self.geo_points:
            self._add_converted_point(geo_point)


def parse_polygon(filename):
    polygon = GeoPolygon()

    root = ET.parse(filename).getroot()
    coordinates = root.find('.//{http://www.opengis.net/kml/2.2}coordinates')
    if coordinates is None:
        raise RuntimeError(f"No coordinates tag in the KML file: {filename}")

    # try to split by lines or by spaces
    coord_strings = coordinates.text.strip().split('\n')
    if len(coord_strings) < 2:
        coord_strings = coord_strings[0].split(' ')

    for coords in coord_strings:
        point = tuple(map(float, coords.strip().split(',')))
        polygon.add_geo_point(point)

    if not len(polygon.geo_points):
        raise RuntimeError(f"No points in the coordinate list for the KML file: {filename}")

    polygon.set_origin(polygon.geo_points[0])

    return polygon
