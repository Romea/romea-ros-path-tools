import numpy as np
import matplotlib.pyplot as plt

from .path_v2 import Path


def plot_path(path: Path, handles: dict = {}, offset: np.ndarray = (0, 0)):
  points = path.positions()[:, 0:2] + offset

  color_it = plt.rcParams['axes.prop_cycle']()
  zones = {}
  for a in path.annotations:
    if 'point_index' in a:
      index = a['point_index']
      value = a['value']
      if a['type'] in ['zone_enter', 'zone_exit']:
        if value not in zones:
          zones[value] = []
        zones[value].append(index)

  for zone, delim in zones.items():
    color = next(color_it)['color']
    for begin, end in zip(delim[::2], delim[1::2]):
      handles[zone], = plt.plot(points[begin:end + 1, 0], points[begin:end + 1, 1], '-',
          linewidth=13, 
          alpha=0.3, 
          color=color,
          solid_capstyle='butt')

  handles[path.name], = plt.plot(points[:, 0], points[:, 1], '.-', markersize=4)
  
  # Draw an arrow at the end
  end_segment = points[-2:, 0:2]
  delta_arrow = np.diff(end_segment, axis=0)
  plt.arrow(*end_segment[0], *delta_arrow[0], head_width=.5, 
      edgecolor='none', facecolor=handles[path.name].get_color())
