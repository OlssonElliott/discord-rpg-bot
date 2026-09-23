"""Pillow renderer for already-filtered player dungeon maps."""

from io import BytesIO

from PIL import Image, ImageDraw

from ..world.dungeon import PlayerMap
from .assets import (
    BROKEN_LOCK_ART_PATH,
    CONNECTION_ART_HEIGHT,
    DOOR_ART_PATH,
    HALLWAY_ART_PATH,
    LOCKED_ART_PATH,
    LOCK_ART_GAP,
    LOCK_ART_HEIGHT,
    MAP_BACKGROUND_PATH,
    MAP_HEIGHT,
    MAP_WIDTH,
    OPEN_DOOR_ART_PATH,
    ROOM_ART_PATH,
    TRAP_ART_GAP,
    TRAP_ART_HEIGHT,
    TRAP_ART_PATH,
    TRAP_DISARMED_ART_PATH,
    TRAP_TRIGGERED_ART_PATH,
    UNLOCKED_ART_PATH,
    _door_visual_anchor,
    _loaded_broken_lock_art,
    _loaded_disarmed_trap_art,
    _loaded_door_art,
    _loaded_hallway_art,
    _loaded_locked_art,
    _loaded_map_background,
    _loaded_open_door_art,
    _loaded_room_art,
    _loaded_trap_art,
    _loaded_triggered_trap_art,
    _loaded_unlocked_art,
    _open_door_visual_anchor,
)
from .connectors import (
    _door_marker_layout,
    _draw_connections,
    _draw_connector_art,
    _draw_connector_dot,
    _prepared_marker_art,
    _trap_marker_position,
)
from .layout import (
    CONNECTION_ROOM_GAP,
    MIN_ROOM_HEIGHT,
    MIN_ROOM_WIDTH,
    PADDING,
    VIEWPORT_BOUNDS,
    WORLD_TO_MAP_SCALE,
    _edge_point,
    _focus_distances,
    _layout,
    _point_toward,
)
from .rooms import (
    _draw_room_art,
    _draw_rooms,
    _draw_room_label,
    _fog_colour,
    _fog_room,
    _fog_strength,
    _nine_slice,
    _player_markers,
    _room_texture,
    _wrap_label,
)
from .canvas import (
    _dark_fantasy_backdrop,
    _font,
    _map_canvas,
    _png,
)


def render_player_map(view: PlayerMap) -> BytesIO:
    """Render only the rooms and connections contained in ``view``."""
    image = _map_canvas()
    draw = ImageDraw.Draw(image)
    title_font = _font(42, heading=True)
    room_font = _font(30, heading=True)
    mystery_font = _font(58, heading=True)
    small_font = _font(19)
    marker_font = _font(18, heading=True)

    numbered_floor = f"Floor {view.floor.floor_number}"
    floor_title = (
        view.floor.name
        if view.floor.name.casefold() == numbered_floor.casefold()
        else f"{view.floor.name}  |  {numbered_floor}"
    )
    draw.text(
        (PADDING, 54),
        floor_title,
        fill="#e7d7b5",
        font=title_font,
    )
    title_box = draw.textbbox((PADDING, 54), floor_title, font=title_font)
    divider_end = min(title_box[2] + 90, MAP_WIDTH - PADDING)
    draw.line(
        (PADDING, title_box[3] + 10, divider_end, title_box[3] + 10),
        fill="#9a783d",
        width=3,
    )
    if not view.rooms:
        draw.text(
            (PADDING, 135),
            "The darkness has yielded no known paths on this floor.",
            fill="#aa9c83",
            font=room_font,
        )
        return _png(image)

    map_base = image.copy()
    positions = _layout(view)
    focus_distances = _focus_distances(view)
    _draw_connections(
        image,
        draw,
        view,
        positions,
        focus_distances,
        small_font,
    )

    _draw_rooms(
        image,
        draw,
        view,
        positions,
        focus_distances,
        room_font,
        mystery_font,
        marker_font,
    )

    # A camera may place distant known rooms beyond the visible region. Restore
    # the decorated canvas outside the viewport so those rooms and connectors
    # cannot draw over the floor title or the outer map frame.
    outside_viewport = Image.new("L", (MAP_WIDTH, MAP_HEIGHT), 255)
    try:
        ImageDraw.Draw(outside_viewport).rectangle(VIEWPORT_BOUNDS, fill=0)
        image.paste(map_base, (0, 0), outside_viewport)
    finally:
        outside_viewport.close()
        map_base.close()

    return _png(image)
