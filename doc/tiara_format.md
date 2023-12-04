## Example

Here is an example of a TIARA trajectory file:

```json
{
  "version": "1",
  "origin": {
    "type": "WGS84",
    "coordinates": [ 46.3404013, 3.4368485, 279.277 ]
  },
  "points": {
    "columns": [ "x", "y", "speed" ],
    "values": [
      [  -9.005,  4.017,  1.005 ],
      [ -10.342,  2.836,  1.017 ],
      [ -12.382,  2.709,  0.985 ],
      [ -13.875,  3.68,   1.002 ],
      [ -14.567,  5.498,  0.988 ],
      [ -14.006,  7.315,  1.004 ],
      [ -12.743,  8.842,  1.003 ],
      [ -11.151, 10.041,  0.995 ],
      [ -10.019, 11.583,  1.002 ],
      [  -9.157, 13.183,  1.019 ],
      [  -7.379, 14.342,  0.991 ],
      [  -5.377, 14.407,  1.012 ],
      [  -3.273, 13.842,  1.0   ],
      [  -4.338, 14.628, -0.741 ],
      [  -5.035, 16.465, -0.973 ],
      [  -4.973, 17.525, -0.845 ],
      [  -6.659, 16.367,  0.984 ],
      [  -8.562, 16.205,  1.0   ],
      [ -10.481, 16.16,   1.0   ],
      [ -11.851, 16.209,  0.998 ]
    ]
  },
  "sections": [ 0, 13, 16 ],
  "annotations": [
    {
      "type": "zone_enter",
      "point_index": 3,
      "value": "example_zone1"
    },
    {
      "type": "zone_exit",
      "point_index": 8,
      "value": "example_zone1"
    }
  ]
}
```

The corresponding image of the trajectory (obtained with the tool `show`) is:

![]() <img src="doc/data/example_traj.png" width="300"/>


## Description of the format

A trajectory contains a list of points expressed in a Cartesian space (x, y and possibly z) and can include other informations that can be specified as an additional column in the list of points or as an annotation.
Here is a minimalist trajectory example that can work with every available tools in `romea_path_tools`:
```json
{
  "version": "1",
  "origin": {
    "type": "WGS84",
    "coordinates": [ 0, 0, 0 ]
  },
  "points": {
    "columns": [ "x", "y" ],
    "values": [
      [ 0, 0 ],
      [ 1, 0 ]
    ]
  },
  "sections": [ 0 ]
}
```

This file format correspond to a JSON file with the extension `.traj`. The root element must be an object and must include the fields `version`, `origin`, `points` and `sections`.
A tiara trajectory may also include an optional field `annotations`.
These fields are described in the following sections.


### version

```json
"version": "1"
```
The `version` field specifies the version of the TIARA format used by this file.
It allows the future versions of this format to make important changes that may break the backward compatibility but continue to handle the file written in an older version of this format.
Currently, the only supported version is `"1"`.


### origin

```json
"origin": {
  "type": "WGS84",
  "coordinates": [ 46.1234, 3.5678, 286.37 ]
}
```
The `origin` field contains the information necessary to make the link between the geographic coordinate system and the points of the trajectory that are specified in a Cartesian space. The `coordinates` corresponds to the position of the point (0, 0) expressed in one of the geographic coordinate system specified by the `type` field.
The only supported type is `WGS84` and the columns of the `coordinates` correspond to `[latitude, longitude, altitude]`.


### points

```json
"points": {
  "columns": [ "x", "y", "speed", "something_else" ],
  "values": [
    [ 0, 0, 3.1, 145.2 ],
    [ 1, 0, 3.7, 367.7 ]
  ]
}
```
The `points` field contains the (x, y) coordinates of each point of the trajectory but can also include other informations like `speed`, `z`, `roll`, `pitch` or anything the user want to record with the trajectory. The sub-field `columns` specifies the list of features to record for each point. This list must include `x` and `y` but the order of the columns is not important as long as the recorded data matches. However, it is better to put the `x` and `y` columns first to improve readability. It is also required to give at least two points, in order to correctly draw the trajectory.


### sections

```json
"sections": [ 0, 37, 74, 135 ]
```
The `sections` field allows to cut the trajectory into several sections that correspond to different part of the trajectory. For example, a new section is created each time the robot changes direction (forward or backward). The `sections` contains the list of point index that correspond to the beginning of each section. The beginning of the first section must be specified, so the minimal valid list is `[ 0 ]` and corresponds to a trajectory with only one section.


### annotations

```json
"annotations": []
```
The `annotations` field is a list of JSON object that describe information linked to the trajectory. The current version of this format can only handle information linked to a specific point of the trajectory. The different types of annotation are described below.

##### zone of the trajectory

```json
  "annotations": [
    {
      "type": "zone_enter",
      "point_index": 3,
      "value": "example_zone1"
    },
    {
      "type": "zone_exit",
      "point_index": 8,
      "value": "example_zone1"
    }
  ]
```

To specify information linked to a zone of the trajectory, it is possible to use a pair of annotations that specify the beginning of zone: `"type": "zone_enter"` and the end of the zone: `"type": "zone_exit"`. Each of this annotation must also include a `point_index` that specify the index of the point linked to each annotation and a `value` field that must be identical in both annotations.
