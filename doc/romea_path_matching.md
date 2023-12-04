This package contains a ROS node used to localize a robot on a loaded trajectory.
The input data are:

* the trajectory (loaded from a file by using the `romea_path` library)
* the robot localization

The output data are:

* the matching points of the trajectory composed of
  - the lateral and angular deviation (coordinates in a Frenet pose)
  - the posture of the point (x, y, curvature, dot curvature)
* the robot velocity
