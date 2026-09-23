"""Connector marker rendering for dungeon maps."""

from math import hypot

from PIL import Image, ImageDraw, ImageEnhance

from ..world.dungeon import ConnectionType, PlayerMap, TrapState
from .assets import (
    LOCK_ART_GAP,
    TRAP_ART_GAP,
    _door_visual_anchor,
    _loaded_broken_lock_art,
    _loaded_disarmed_trap_art,
    _loaded_door_art,
    _loaded_hallway_art,
    _loaded_locked_art,
    _loaded_open_door_art,
    _loaded_trap_art,
    _loaded_triggered_trap_art,
    _loaded_unlocked_art,
    _open_door_visual_anchor,
)

from .layout import _edge_point, _point_toward
from .rooms import _fog_colour, _fog_strength


def _draw_connector_art(
    image: Image.Image,
    midpoint: tuple[float, float],
    connection_type: ConnectionType,
    *,
    has_lock: bool = False,
    is_locked: bool = False,
    is_broken: bool = False,
    is_open: bool = False,
    has_trap: bool = False,
    trap_state: TrapState | None = None,
    fog_strength: float,
    vertical: bool = False,
) -> bool:
    """Place the selected, unrotated artwork at a connector midpoint."""
    if connection_type is ConnectionType.DOOR:
        source = _loaded_open_door_art() if is_open else _loaded_door_art()
    elif connection_type in (ConnectionType.HALLWAY, ConnectionType.PASSAGE):
        source = _loaded_hallway_art()
    else:
        source = None
    if source is None:
        return False
    trap_art = None
    if has_trap:
        if trap_state is TrapState.DISARMED:
            trap_art = _loaded_disarmed_trap_art()
        elif trap_state is TrapState.TRIGGERED:
            trap_art = _loaded_triggered_trap_art()
        else:
            trap_art = _loaded_trap_art()
    if connection_type is ConnectionType.DOOR:
        lock_art = None
        if has_lock:
            if is_broken:
                lock_art = _loaded_broken_lock_art()
            elif is_locked:
                lock_art = _loaded_locked_art()
            else:
                lock_art = _loaded_unlocked_art()
        scale, door_position, lock_position = _door_marker_layout(
            midpoint,
            source.size,
            lock_art.size if lock_art is not None else (0, 0),
            vertical=vertical,
            door_visual_anchor=(
                _open_door_visual_anchor() if is_open else _door_visual_anchor()
            ),
        )
        artwork = _prepared_marker_art(source, scale, fog_strength)
        image.paste(artwork, door_position, artwork)
        if lock_art is not None and lock_position is not None:
            rendered_lock = _prepared_marker_art(lock_art, scale, fog_strength)
            image.paste(rendered_lock, lock_position, rendered_lock)
        marker_position = door_position
    else:
        artwork = _prepared_marker_art(source, 1.0, fog_strength)
        left = round(midpoint[0] - artwork.width / 2)
        top = round(midpoint[1] - artwork.height / 2)
        marker_position = (left, top)
        image.paste(artwork, marker_position, artwork)
    if trap_art is not None:
        rendered_trap = _prepared_marker_art(trap_art, 1.0, fog_strength)
        trap_position = _trap_marker_position(
            midpoint,
            marker_position,
            artwork.size,
            rendered_trap.size,
            vertical=vertical,
        )
        image.paste(rendered_trap, trap_position, rendered_trap)
    return True


def _trap_marker_position(
    midpoint: tuple[float, float],
    marker_position: tuple[int, int],
    marker_size: tuple[int, int],
    trap_size: tuple[int, int],
    *,
    vertical: bool,
) -> tuple[int, int]:
    """Place traps opposite the lock: right when vertical, below otherwise."""
    if vertical:
        return (
            marker_position[0] + marker_size[0] + TRAP_ART_GAP,
            round(midpoint[1] - trap_size[1] / 2),
        )
    return (
        round(midpoint[0] - trap_size[0] / 2),
        marker_position[1] + marker_size[1] + TRAP_ART_GAP,
    )


def _prepared_marker_art(
    source: Image.Image,
    scale: float,
    fog_strength: float,
) -> Image.Image:
    artwork = source
    if scale < 1:
        artwork = source.resize(
            (
                max(1, round(source.width * scale)),
                max(1, round(source.height * scale)),
            ),
            Image.Resampling.LANCZOS,
        )
    if fog_strength:
        artwork = ImageEnhance.Brightness(artwork).enhance(
            max(0.25, 1 - fog_strength)
        )
    return artwork


def _door_marker_layout(
    midpoint: tuple[float, float],
    door_size: tuple[int, int],
    lock_size: tuple[int, int],
    *,
    vertical: bool = False,
    door_visual_anchor: tuple[float, float] | None = None,
) -> tuple[float, tuple[int, int], tuple[int, int] | None]:
    """Keep the door full-size and place its lock according to line direction."""
    anchor = door_visual_anchor or (
        (door_size[0] - 1) / 2,
        (door_size[1] - 1) / 2,
    )
    door_position = (
        round(midpoint[0] - anchor[0]),
        round(midpoint[1] - anchor[1]),
    )
    if not lock_size[0] or not lock_size[1]:
        return 1.0, door_position, None
    if vertical:
        lock_position = (
            door_position[0] - LOCK_ART_GAP - lock_size[0],
            round(midpoint[1] - lock_size[1] / 2),
        )
    else:
        lock_position = (
            round(midpoint[0] - lock_size[0] / 2),
            door_position[1] - LOCK_ART_GAP - lock_size[1],
        )
    return 1.0, door_position, lock_position


def _draw_connections(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    view: PlayerMap,
    positions: dict[str, tuple[float, float, float, float]],
    focus_distances: dict[str, int],
    small_font,
) -> None:
    """Draw all visible same-floor and cross-floor map connections."""
    centers = {
        room.id: (
            positions[room.id][0] + positions[room.id][2] / 2,
            positions[room.id][1] + positions[room.id][3] / 2,
        )
        for room in view.rooms
    }
    boxes = {
        room.id: (
            positions[room.id][0],
            positions[room.id][1],
            positions[room.id][0] + positions[room.id][2],
            positions[room.id][1] + positions[room.id][3],
        )
        for room in view.rooms
    }

    for connection in view.connections:
        source = centers.get(connection.from_room_id)
        target = centers.get(connection.to_room_id)
        if source and target:
            connection_fog = _fog_strength(
                max(
                    focus_distances.get(connection.from_room_id, 99),
                    focus_distances.get(connection.to_room_id, 99),
                )
            )
            start = _edge_point(source, target, boxes[connection.from_room_id])
            end = _edge_point(target, source, boxes[connection.to_room_id])
            start = _point_toward(start, source, 18)
            end = _point_toward(end, target, 18)
            draw.line(
                (*start, *end),
                fill=_fog_colour("#080706", connection_fog),
                width=13,
            )
            draw.line(
                (*start, *end),
                fill=_fog_colour("#645338", connection_fog),
                width=6,
            )
            draw.line(
                (*start, *end),
                fill=_fog_colour("#9a8051", connection_fog),
                width=2,
            )
            midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            if not _draw_connector_art(
                image,
                midpoint,
                connection.connection_type,
                has_lock=connection.has_lock,
                is_locked=connection.is_locked,
                is_broken=connection.is_broken,
                is_open=connection.is_open,
                has_trap=connection.has_trap,
                trap_state=connection.trap_state,
                fog_strength=connection_fog,
                vertical=abs(target[1] - source[1]) >= abs(target[0] - source[0]),
            ):
                _draw_connector_dot(draw, midpoint, fog_strength=connection_fog)
        else:
            local_id = (
                connection.from_room_id
                if connection.from_room_id in centers
                else connection.to_room_id
            )
            local = centers.get(local_id)
            if local:
                connection_fog = _fog_strength(focus_distances.get(local_id, 99))
                if (
                    connection.from_floor_id == connection.to_floor_id
                    and connection.connection_type is ConnectionType.DOOR
                ):
                    if local_id == connection.from_room_id:
                        dx = (connection.to_x or 0) - (connection.from_x or 0)
                        dy = (connection.to_y or 0) - (connection.from_y or 0)
                    else:
                        dx = (connection.from_x or 0) - (connection.to_x or 0)
                        dy = (connection.from_y or 0) - (connection.to_y or 0)
                    length = hypot(dx, dy)
                    if not length:
                        dx, dy, length = 1.0, 0.0, 1.0
                    projected = (
                        local[0] + dx / length * 200,
                        local[1] + dy / length * 200,
                    )
                    room_edge = _edge_point(local, projected, boxes[local_id])
                    line_start = _point_toward(room_edge, local, 18)
                    door_midpoint = _point_toward(room_edge, projected, 46)
                    draw.line(
                        (*line_start, *door_midpoint),
                        fill=_fog_colour("#080706", connection_fog),
                        width=13,
                    )
                    draw.line(
                        (*line_start, *door_midpoint),
                        fill=_fog_colour("#645338", connection_fog),
                        width=6,
                    )
                    draw.line(
                        (*line_start, *door_midpoint),
                        fill=_fog_colour("#9a8051", connection_fog),
                        width=2,
                    )
                    _draw_connector_art(
                        image,
                        door_midpoint,
                        connection.connection_type,
                        has_lock=connection.has_lock,
                        is_locked=connection.is_locked,
                        is_broken=connection.is_broken,
                        is_open=connection.is_open,
                        has_trap=connection.has_trap,
                        trap_state=connection.trap_state,
                        fog_strength=connection_fog,
                        vertical=abs(dy) >= abs(dx),
                    )
                    continue
                endpoint = (local[0] + 105, local[1] + 80)
                draw.line(
                    (*local, *endpoint),
                    fill=_fog_colour("#090806", connection_fog),
                    width=15,
                )
                draw.line(
                    (*local, *endpoint),
                    fill=_fog_colour("#75603e", connection_fog),
                    width=6,
                )
                other_floor_id = (
                    connection.to_floor_id
                    if local_id == connection.from_room_id
                    else connection.from_floor_id
                )
                connection_name = connection.connection_type.value.replace("_", " ")
                label = f"{connection_name} -> {other_floor_id}"
                draw.text(
                    endpoint,
                    label,
                    fill=_fog_colour("#c7b58e", connection_fog),
                    font=small_font,
                )


def _draw_connector_dot(
    draw: ImageDraw.ImageDraw,
    midpoint: tuple[float, float],
    *,
    fog_strength: float,
) -> None:
    """Retain the classic marker for connection types without artwork."""
    draw.ellipse(
        (midpoint[0] - 8, midpoint[1] - 8, midpoint[0] + 8, midpoint[1] + 8),
        fill=_fog_colour("#655239", fog_strength),
        outline=_fog_colour("#c4a66b", fog_strength),
        width=2,
    )
    draw.ellipse(
        (midpoint[0] - 3, midpoint[1] - 3, midpoint[0] + 3, midpoint[1] + 3),
        fill=_fog_colour("#dbc38b", fog_strength),
    )
