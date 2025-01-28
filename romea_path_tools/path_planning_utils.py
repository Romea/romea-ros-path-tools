import math
import copy
from fields2cover import Path, Point


def dist(a: Point, b: Point):
    return math.sqrt((a.getX() - b.getX())**2 + (a.getY() - b.getY())**2)


def discretize_swaths(path: Path, step_size: float):
    new_path = Path()
    prev_state = path.getStates()[0]

    for state in path.getStates():
        while (distance := dist(prev_state.point, state.point)) > step_size:
            step_state = copy.copy(prev_state)
            prev_p, p = prev_state.point, state.point

            step_coef = step_size / distance
            step_state.point = Point(
                prev_p.getX() + (p.getX() - prev_p.getX()) * step_coef,
                prev_p.getY() + (p.getY() - prev_p.getY()) * step_coef,
                prev_p.getZ() + (p.getZ() - prev_p.getZ()) * step_coef,
            )
            step_state.len = min(step_size, distance)

            new_path.addState(step_state)
            prev_state = step_state

        if distance > 1e-3:
            new_path.addState(state)

        prev_state = state

    return new_path
