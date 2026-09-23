"""Layout and geometry helpers for the dungeon map renderer."""

from collections import deque
from math import hypot

from ..world.dungeon import ConnectionType, PlayerMap
from .assets import (
    MAP_HEIGHT,
    MAP_WIDTH,
    _loaded_door_art,
    _loaded_open_door_art,
)


PADDING = 80
MIN_ROOM_WIDTH = 250
MIN_ROOM_HEIGHT = 160
WORLD_TO_MAP_SCALE = 1.0
VIEWPORT_BOUNDS = (PADDING, 145, MAP_WIDTH - PADDING, MAP_HEIGHT - PADDING)
CONNECTION_ROOM_GAP = 12


def _layout(view: PlayerMap) -> dict[str, tuple[float, float, float, float]]:
    """Project persisted dungeon coordinates through a focus-centred camera."""
    rooms = {room.id: room for room in view.rooms}
    focus = rooms.get(view.focused_room_id or "")
    current = rooms.get(view.current_room_id or "")
    anchor = focus or current
    if anchor is None:
        anchor_x = sum(room.x for room in view.rooms) / len(view.rooms)
        anchor_y = sum(room.y for room in view.rooms) / len(view.rooms)
    else:
        anchor_x, anchor_y = anchor.x, anchor.y

    viewport_left, viewport_top, viewport_right, viewport_bottom = VIEWPORT_BOUNDS
    viewport_center_x = (viewport_left + viewport_right) / 2
    viewport_center_y = (viewport_top + viewport_bottom) / 2
    positioned = {}
    for room in view.rooms:
        width = max(MIN_ROOM_WIDTH, room.width * 85)
        height = max(MIN_ROOM_HEIGHT, room.height * 60)
        center_x = viewport_center_x + (room.x - anchor_x) * WORLD_TO_MAP_SCALE
        center_y = viewport_center_y + (room.y - anchor_y) * WORLD_TO_MAP_SCALE
        positioned[room.id] = (
            center_x - width / 2,
            center_y - height / 2,
            width,
            height,
        )
    _space_door_connections(view, positioned, anchor.id if anchor else None)
    return positioned


def _space_door_connections(
    view: PlayerMap,
    positioned: dict[str, tuple[float, float, float, float]],
    anchor_id: str | None,
) -> None:
    """Move nearby rooms apart so door artwork always remains full-size."""
    doors = tuple(
        door for door in (_loaded_door_art(), _loaded_open_door_art())
        if door is not None
    )
    if not doors:
        return
    required_horizontal_gap = max(door.width for door in doors) + CONNECTION_ROOM_GAP
    required_vertical_gap = max(door.height for door in doors) + CONNECTION_ROOM_GAP
    door_connections = tuple(
        connection
        for connection in view.connections
        if connection.connection_type is ConnectionType.DOOR
        and connection.from_room_id in positioned
        and connection.to_room_id in positioned
    )
    for _ in range(max(1, len(door_connections) * 2)):
        changed = False
        for connection in door_connections:
            first_id = connection.from_room_id
            second_id = connection.to_room_id
            first = positioned[first_id]
            second = positioned[second_id]
            first_center = (first[0] + first[2] / 2, first[1] + first[3] / 2)
            second_center = (
                second[0] + second[2] / 2,
                second[1] + second[3] / 2,
            )
            vertical = abs(second_center[1] - first_center[1]) >= abs(
                second_center[0] - first_center[0]
            )
            if vertical:
                upper_id, lower_id = (
                    (first_id, second_id)
                    if first_center[1] <= second_center[1]
                    else (second_id, first_id)
                )
                upper = positioned[upper_id]
                lower = positioned[lower_id]
                gap = lower[1] - (upper[1] + upper[3])
                deficit = required_vertical_gap - gap
                if deficit > 0:
                    positioned[upper_id] = (
                        upper[0],
                        upper[1] - deficit,
                        upper[2],
                        upper[3],
                    )
                    changed = True
            else:
                left_id, right_id = (
                    (first_id, second_id)
                    if first_center[0] <= second_center[0]
                    else (second_id, first_id)
                )
                left = positioned[left_id]
                right = positioned[right_id]
                gap = right[0] - (left[0] + left[2])
                deficit = required_horizontal_gap - gap
                if deficit > 0:
                    positioned[left_id] = (
                        left[0] - deficit,
                        left[1],
                        left[2],
                        left[3],
                    )
                    changed = True
        if not changed:
            break

    if anchor_id in positioned:
        anchor = positioned[anchor_id]
        viewport_center = (
            (VIEWPORT_BOUNDS[0] + VIEWPORT_BOUNDS[2]) / 2,
            (VIEWPORT_BOUNDS[1] + VIEWPORT_BOUNDS[3]) / 2,
        )
        offset_x = viewport_center[0] - (anchor[0] + anchor[2] / 2)
        offset_y = viewport_center[1] - (anchor[1] + anchor[3] / 2)
        for room_id, (left, top, width, height) in positioned.items():
            positioned[room_id] = (
                left + offset_x,
                top + offset_y,
                width,
                height,
            )


def _focus_distances(view: PlayerMap) -> dict[str, int]:
    """Return graph distance from focus without changing room knowledge."""
    room_ids = {room.id for room in view.rooms}
    focus_id = (
        view.focused_room_id
        if view.focused_room_id in room_ids
        else view.current_room_id
        if view.current_room_id in room_ids
        else None
    )
    if focus_id is None:
        return {room_id: 0 for room_id in room_ids}
    neighbours = {room_id: set() for room_id in room_ids}
    for connection in view.connections:
        if (
            connection.from_room_id in room_ids
            and connection.to_room_id in room_ids
        ):
            neighbours[connection.from_room_id].add(connection.to_room_id)
            neighbours[connection.to_room_id].add(connection.from_room_id)
    distances = {focus_id: 0}
    pending = deque((focus_id,))
    while pending:
        room_id = pending.popleft()
        for neighbour in neighbours[room_id]:
            if neighbour in distances:
                continue
            distances[neighbour] = distances[room_id] + 1
            pending.append(neighbour)
    return distances


def _edge_point(
    origin: tuple[float, float],
    target: tuple[float, float],
    box: tuple[float, float, float, float],
) -> tuple[float, float]:
    """Find where a center-to-center path meets a room's rectangular edge."""
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    half_width = max(1.0, (box[2] - box[0]) / 2)
    half_height = max(1.0, (box[3] - box[1]) / 2)
    factor = min(
        1.0,
        1.0 / max(abs(dx) / half_width, abs(dy) / half_height, 1e-9),
    )
    return origin[0] + dx * factor, origin[1] + dy * factor


def _point_toward(
    point: tuple[float, float],
    target: tuple[float, float],
    distance: float,
) -> tuple[float, float]:
    """Move a connector endpoint toward a room center by ``distance``."""
    dx = target[0] - point[0]
    dy = target[1] - point[1]
    length = hypot(dx, dy)
    if length == 0:
        return point
    scale = min(1.0, distance / length)
    return point[0] + dx * scale, point[1] + dy * scale
