from dataclasses import dataclass, astuple
from pymap3d import enu
import numpy as np

# local
from .kml import Kml

@dataclass
class Point:
  x: float
  y: float
  speed: float
  marker_count: int
  nb_cols: int

  def __repr__(self):
    return f'{self.x:.3f} {self.y:.3f} {self.speed:.3f} {self.marker_count}'

  @staticmethod
  def from_str(s):
    v = s.split(' ')
    if len(v) == 2:
      return Point(float(v[0]), float(v[1]), 0, 0, 4)
    elif len(v) == 3:
      return Point(float(v[0]), float(v[1]), float(v[2]), 0, 4)
    else:
      return Point(float(v[0]), float(v[1]), float(v[2]), int(v[3]), 4)


class RomeaPath:
  def __init__(self):
    self.sections = []
    self.anchor = (0, 0, 0)
    self.markers = []


  @staticmethod
  def load(traj_filename):
    path = RomeaPath()

    with open(traj_filename, 'r') as f:
      f.readline()

      line = f.readline()
      path.anchor = list(map(float, line.split(' ')))

      nb_sections = int(f.readline())
      prev_marker_count = 0

      for section_index in range(nb_sections):
        points = []
        nb_lines = int(f.readline().split(' ')[0])

        for line_index in range(nb_lines):
          point = Point.from_str(f.readline())
          points.append(point)

          if point.nb_cols >= 4:
            marker_count = int(point.marker_count)
            if marker_count != prev_marker_count:
              path.markers.append(points[-1])
            prev_marker_count = marker_count

        path.sections.append(points)

    return path


  def save(self, filename):
    with open(filename, 'w') as f:
      f.write('WGS84\n')
      f.write(f'{self.anchor[0]} {self.anchor[1]} {self.anchor[2]}\n')
      f.write(f'{len(self.sections)}\n')

      for points in self.sections:
        if len(points):
          f.write(f'{len(points)} {points[0].nb_cols}\n')

          for point in points:
            f.write(f'{point}\n')


  def save_csv(self, filename):
    with open(filename, 'w') as f:
      f.write(f'x,y,speed,marker_count\n')

      for points in self.sections:
        for p in points:
          f.write(f'{p.x},{p.y},{p.speed},{p.marker_count}\n')


  def save_wgs84_csv(self, filename):
    with open(filename, 'w') as f:
      f.write(f'latitude,longitude,altitude\n')

      for points in self.sections:
        for p in points:
          lat, lon, alt = enu.enu2geodetic(p.x, p.y, 0, *self.anchor)
          f.write(f'{lat},{lon},{alt}\n')


  def save_kml(self, filename):
    kml = Kml()
    for points in self.sections:
      for p in points:
        lat, lon, alt = enu.enu2geodetic(p.x, p.y, 0, *self.anchor)
        kml.add_point(lon, lat, alt)

    kml.save(filename)


  def array(self):
    points = []
    for section in self.sections:
      for p in section:
        points.append(astuple(p)[:-1])
    return np.array(points)


  def wgs84_array(self):
    points = []
    for section in self.sections:
      for p in section:
        lat, lon, alt = enu.enu2geodetic(p.x, p.y, 0, *self.anchor)
        points.append((lat, lon, alt))
    return points
