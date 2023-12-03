import math
from fields2cover import Path, PathState, Point


def dist(a: Point, b: Point):
    return math.sqrt((a.getX() - b.getX())**2 + (a.getY() - b.getY())**2)


def discretize_swaths(path: Path, step_size: float):
    new_path = Path()

    # Loop through all the points in the path
    for i in range(len(path.states) - 1):
        start_point = path.states[i].point
        end_point = path.states[i + 1].point

        distance = dist(end_point, start_point)
        number_of_steps = math.fabs(distance / step_size)
        rounded_number_of_steps = round(number_of_steps)

        # If rounded number of steps is equal to zero, then the provided step_size is greater
        # than the distance. In this case, set the number of steps to 1, thus do not discretize
        # the path
        if rounded_number_of_steps == 0:
            rounded_number_of_steps = 1

        dx_coef = (end_point.getX() - start_point.getX()) / rounded_number_of_steps
        dy_coef = (end_point.getY() - start_point.getY()) / rounded_number_of_steps
        dz_coef = (end_point.getZ() - start_point.getZ()) / rounded_number_of_steps

        # Iterate over each pair of coordinates and add them as states into our new Path object
        for j in range(rounded_number_of_steps + 1):
            # Create a new PathState object
            state = PathState()

            # Update point with incremental step values
            state.point = Point(
                start_point.getX() + j * dx_coef,
                start_point.getY() + j * dy_coef,
                start_point.getZ() + j * dz_coef,
            )

            state.angle = path.states[i].angle
            state.velocity = path.states[i].velocity
            state.duration = float(distance / state.velocity / rounded_number_of_steps)
            state.dir = path.states[i].dir
            state.type = path.states[i].type

            new_path.states.append(state)

    return new_path
