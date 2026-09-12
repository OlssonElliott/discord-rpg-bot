"""Pillow renderer for already-filtered player dungeon maps."""

from collections import deque
from functools import lru_cache
from io import BytesIO
from math import hypot
from pathlib import Path
from random import Random

from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFont

from .dungeon import KnowledgeState, PlayerMap


MAP_WIDTH = 1600
MAP_HEIGHT = 1000
PADDING = 80
MIN_ROOM_WIDTH = 250
MIN_ROOM_HEIGHT = 160
WORLD_TO_MAP_SCALE = 1.0
VIEWPORT_BOUNDS = (PADDING, 145, MAP_WIDTH - PADDING, MAP_HEIGHT - PADDING)
MAP_BACKGROUND_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "map" / "background.png"
)
ROOM_ART_PATH = Path(__file__).resolve().parents[1] / "assets" / "map" / "room.png"


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
            # Run beneath each room frame so antialiased/shadow pixels cannot
            # leave a visible gap between the connector and the artwork.
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
            draw.ellipse(
                (midpoint[0] - 8, midpoint[1] - 8, midpoint[0] + 8, midpoint[1] + 8),
                fill=_fog_colour("#655239", connection_fog),
                outline=_fog_colour("#c4a66b", connection_fog),
                width=2,
            )
            draw.ellipse(
                (midpoint[0] - 3, midpoint[1] - 3, midpoint[0] + 3, midpoint[1] + 3),
                fill=_fog_colour("#dbc38b", connection_fog),
            )
        else:
            local_id = (
                connection.from_room_id
                if connection.from_room_id in centers
                else connection.to_room_id
            )
            local = centers.get(local_id)
            if local:
                connection_fog = _fog_strength(focus_distances.get(local_id, 99))
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

    for room in view.rooms:
        left, top, width, height = positions[room.id]
        box = (left, top, left + width, top + height)
        visited = room.knowledge_state is KnowledgeState.VISITED
        fill = "#352d24" if visited else "#1d1b18"
        outline = "#8d7650" if visited else "#504a41"
        border_width = 6
        if room.is_focused:
            outline = "#d8c89f"
            border_width = 9
        if room.is_current:
            outline = "#c69a4b"
            border_width = 13
        uses_room_art = _draw_room_art(image, box, visited=visited)
        if not uses_room_art:
            draw.rounded_rectangle(
                (left + 10, top + 12, left + width + 10, top + height + 12),
                radius=18,
                fill="#090806",
            )
            draw.rounded_rectangle(box, radius=18, fill=fill)
            _room_texture(draw, box, room.id, visited)
        if not uses_room_art or room.is_current or room.is_focused:
            status_box = (
                left + (11 if uses_room_art else 0),
                top + (11 if uses_room_art else 0),
                left + width - (11 if uses_room_art else 0),
                top + height - (11 if uses_room_art else 0),
            )
            draw.rounded_rectangle(
                status_box, radius=18, outline=outline, width=border_width
            )
        if room.is_current and room.is_focused:
            inset_box = (
                left + 16,
                top + 16,
                left + width - 16,
                top + height - 16,
            )
            draw.rounded_rectangle(
                inset_box, radius=12, outline="#d8c89f", width=5
            )
        if room.knowledge_state is KnowledgeState.KNOWN:
            # A dashed inner border reinforces uncertainty even without colour.
            _dashed_rectangle(draw, box, "#716858")
            _draw_room_label(
                draw,
                "?",
                box,
                mystery_font,
                "#9b9282",
            )
        else:
            _draw_room_label(
                draw,
                room.display_name,
                box,
                room_font,
                "#ece0c6",
            )
        if room.visible_characters:
            _player_markers(draw, box, room.visible_characters, marker_font)
        fog_strength = _fog_strength(focus_distances.get(room.id, 99))
        if fog_strength:
            _fog_room(image, box, fog_strength)

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


@lru_cache(maxsize=1)
def _loaded_map_background() -> Image.Image | None:
    """Load and size the packaged map background once per process."""
    try:
        with Image.open(MAP_BACKGROUND_PATH) as source:
            return source.convert("RGB").resize(
                (MAP_WIDTH, MAP_HEIGHT), Image.Resampling.LANCZOS
            )
    except (OSError, ValueError):
        return None


def _map_canvas() -> Image.Image:
    """Return a fresh map canvas, falling back if the asset is unavailable."""
    background = _loaded_map_background()
    if background is not None:
        return background.copy()

    image = Image.new("RGB", (MAP_WIDTH, MAP_HEIGHT), "#15120f")
    _dark_fantasy_backdrop(ImageDraw.Draw(image))
    return image


@lru_cache(maxsize=1)
def _loaded_room_art() -> Image.Image | None:
    """Load the supplied room frame without its transparent outer margin."""
    try:
        with Image.open(ROOM_ART_PATH) as source:
            room = source.convert("RGBA")
        alpha = room.getchannel("A")
        visible_bounds = alpha.point(
            lambda value: 255 if value >= 16 else 0
        ).getbbox()
        if visible_bounds is None:
            return None
        return room.crop(visible_bounds)
    except (OSError, ValueError):
        return None


def _draw_room_art(
    image: Image.Image,
    box: tuple[float, float, float, float],
    *,
    visited: bool,
) -> bool:
    """Draw the supplied room art while preserving its border proportions."""
    source = _loaded_room_art()
    if source is None:
        return False
    if not visited:
        source = ImageEnhance.Brightness(source).enhance(0.52)

    left, top, right, bottom = (round(value) for value in box)
    room = _nine_slice(source, (max(1, right - left), max(1, bottom - top)))
    image.paste(room, (left, top), room)
    return True


def _nine_slice(source: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize framed art without stretching its corners and edge thickness."""
    target_width, target_height = size
    source_border = min(76, source.width // 3, source.height // 3)
    target_border = min(42, target_width // 3, target_height // 3)
    result = Image.new("RGBA", size, (0, 0, 0, 0))

    source_x = (0, source_border, source.width - source_border, source.width)
    source_y = (0, source_border, source.height - source_border, source.height)
    target_x = (0, target_border, target_width - target_border, target_width)
    target_y = (0, target_border, target_height - target_border, target_height)
    for row in range(3):
        for column in range(3):
            source_box = (
                source_x[column],
                source_y[row],
                source_x[column + 1],
                source_y[row + 1],
            )
            target_box = (
                target_x[column],
                target_y[row],
                target_x[column + 1],
                target_y[row + 1],
            )
            target_size = (
                target_box[2] - target_box[0],
                target_box[3] - target_box[1],
            )
            if target_size[0] <= 0 or target_size[1] <= 0:
                continue
            tile = source.crop(source_box).resize(target_size, Image.Resampling.LANCZOS)
            result.paste(tile, target_box[:2], tile)
    return result


def _dark_fantasy_backdrop(draw: ImageDraw.ImageDraw) -> None:
    """Paint a fallback stone-and-brass frame if the asset is unavailable."""
    for y in range(MAP_HEIGHT):
        shade = 20 + int(8 * y / MAP_HEIGHT)
        draw.line((0, y, MAP_WIDTH, y), fill=(shade, shade - 3, shade - 7))
    random = Random(7319)
    for _ in range(4200):
        x = random.randrange(MAP_WIDTH)
        y = random.randrange(MAP_HEIGHT)
        value = random.choice((24, 27, 30, 34, 38))
        draw.point((x, y), fill=(value, value - 4, value - 8))
    for _ in range(95):
        x = random.randrange(55, MAP_WIDTH - 55)
        y = random.randrange(55, MAP_HEIGHT - 55)
        length = random.randrange(12, 70)
        draw.line(
            (x, y, min(MAP_WIDTH - 55, x + length), y + random.choice((-2, -1, 1, 2))),
            fill=random.choice(("#211d18", "#2b251e", "#171411")),
            width=1,
        )

    # Quiet edge darkening keeps attention on the map without a visible effect layer.
    for inset in range(18):
        shade = 12 + inset // 3
        draw.rectangle(
            (inset, inset, MAP_WIDTH - inset - 1, MAP_HEIGHT - inset - 1),
            outline=(shade, max(7, shade - 3), max(5, shade - 6)),
        )

    outer = (28, 20, MAP_WIDTH - 28, MAP_HEIGHT - 20)
    inner = (42, 34, MAP_WIDTH - 42, MAP_HEIGHT - 34)
    draw.rounded_rectangle(outer, radius=22, outline="#332a20", width=8)
    draw.rounded_rectangle(inner, radius=18, outline="#84683a", width=3)
    for x, y, sx, sy in (
        (50, 42, 1, 1),
        (MAP_WIDTH - 50, 42, -1, 1),
        (50, MAP_HEIGHT - 42, 1, -1),
        (MAP_WIDTH - 50, MAP_HEIGHT - 42, -1, -1),
    ):
        draw.line((x, y, x + sx * 34, y), fill="#b08b4b", width=4)
        draw.line((x, y, x, y + sy * 34), fill="#b08b4b", width=4)
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#b08b4b")


def _room_texture(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    room_id: str,
    visited: bool,
) -> None:
    """Add quiet material detail while keeping labels and state borders clear."""
    left, top, right, bottom = box
    inset = 18
    line_colour = "#44392c" if visited else "#29231e"
    for y in range(int(top + inset), int(bottom - inset), 22):
        draw.line(
            (left + inset, y, right - inset, y),
            fill=line_colour,
            width=2,
        )
    draw.line(
        (left + 22, top + 17, right - 22, top + 17),
        fill="#5a4b38" if visited else "#302c26",
        width=2,
    )
    draw.line(
        (left + 20, bottom - 17, right - 20, bottom - 17),
        fill="#201b17" if visited else "#151310",
        width=3,
    )
    random = Random(sum((index + 1) * ord(char) for index, char in enumerate(room_id)))
    speck_colour = "#584a37" if visited else "#352e27"
    for _ in range(36):
        x = random.uniform(left + inset, max(left + inset, right - inset))
        y = random.uniform(top + inset, max(top + inset, bottom - inset))
        draw.point((x, y), fill=speck_colour)
    for _ in range(8):
        edge_x = random.uniform(left + 24, right - 24)
        edge_y = random.choice((top + 5, bottom - 5))
        draw.line(
            (edge_x - 5, edge_y, edge_x + 5, edge_y),
            fill="#201b17" if visited else "#171411",
            width=2,
        )

    cap_colour = "#b2945d" if visited else "#796d58"
    cap = min(24, max(10, (right - left) / 8))
    for x, y, sx, sy in (
        (left + 8, top + 8, 1, 1),
        (right - 8, top + 8, -1, 1),
        (left + 8, bottom - 8, 1, -1),
        (right - 8, bottom - 8, -1, -1),
    ):
        draw.line((x, y, x + sx * cap, y), fill=cap_colour, width=3)
        draw.line((x, y, x, y + sy * cap), fill=cap_colour, width=3)


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
    return positioned


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


def _fog_strength(distance: int) -> float:
    if distance <= 1:
        return 0.0
    if distance == 2:
        return 0.18
    if distance == 3:
        return 0.42
    return 0.68


def _fog_colour(colour: str, strength: float) -> tuple[int, int, int]:
    source = ImageColor.getrgb(colour)
    fog = (8, 9, 9)
    return tuple(
        round(channel * (1 - strength) + fog_channel * strength)
        for channel, fog_channel in zip(source, fog, strict=True)
    )


def _fog_room(
    image: Image.Image,
    box: tuple[float, float, float, float],
    strength: float,
) -> None:
    left = max(0, round(box[0]))
    top = max(0, round(box[1]))
    right = min(image.width, round(box[2]))
    bottom = min(image.height, round(box[3]))
    if left >= right or top >= bottom:
        return
    region = image.crop((left, top, right, bottom))
    try:
        fog = Image.new("RGB", region.size, (8, 9, 9))
        try:
            fogged = Image.blend(region, fog, strength)
            try:
                image.paste(fogged, (left, top))
            finally:
                fogged.close()
        finally:
            fog.close()
    finally:
        region.close()


def _player_markers(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    names: tuple[str, ...],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """Draw compact fantasy-map occupant tokens without covering the room name."""
    left, _top, right, bottom = box
    diameter = 38
    gap = 8
    capacity = max(1, int((right - left - 36 + gap) // (diameter + gap)))
    visible = list(names[:capacity])
    overflow = len(names) - len(visible)
    if overflow and visible:
        visible[-1] = f"+{overflow + 1}"

    for index, name in enumerate(visible):
        x = left + 18 + index * (diameter + gap)
        y = bottom - diameter - 16
        own_character = index == 0
        if own_character:
            # A tiny compass crest makes the player's token read as a map marker.
            center_x = x + diameter / 2
            draw.polygon(
                (
                    (center_x, y - 7),
                    (center_x + 6, y + 2),
                    (center_x, y + 7),
                    (center_x - 6, y + 2),
                ),
                fill="#d8b45e",
                outline="#241713",
            )
        draw.ellipse(
            (x, y, x + diameter, y + diameter),
            fill="#7a2d27" if own_character else "#423a30",
            outline="#e0bd68" if own_character else "#b9aa8d",
            width=4 if own_character else 3,
        )
        if own_character:
            draw.ellipse(
                (x + 6, y + 6, x + diameter - 6, y + diameter - 6),
                outline="#b8893f",
                width=2,
            )
        label = name if name.startswith("+") else (name[:1].upper() or "?")
        label_box = draw.textbbox((0, 0), label, font=font)
        label_width = label_box[2] - label_box[0]
        label_height = label_box[3] - label_box[1]
        draw.text(
            (
                x + (diameter - label_width) / 2,
                y + (diameter - label_height) / 2 - 2,
            ),
            label,
            fill="#f3e3bd",
            font=font,
        )


def _draw_room_label(
    draw: ImageDraw.ImageDraw,
    label: str,
    box: tuple[float, float, float, float],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    colour: str,
) -> None:
    """Wrap and geometrically center a label inside the complete room."""
    left, top, right, bottom = box
    lines = _wrap_label(draw, label, font, right - left - 42, max_lines=3)
    text_boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_gap = 5
    text_height = sum(box[3] - box[1] for box in text_boxes)
    text_height += line_gap * max(0, len(lines) - 1)
    text_top = (top + bottom - text_height) / 2

    for line, text_box in zip(lines, text_boxes, strict=True):
        text_width = text_box[2] - text_box[0]
        glyph_height = text_box[3] - text_box[1]
        draw.text(
            (
                left + (right - left - text_width) / 2 - text_box[0],
                text_top - text_box[1],
            ),
            line,
            fill=colour,
            font=font,
            stroke_width=1,
            stroke_fill="#17130f",
        )
        text_top += glyph_height + line_gap


def _wrap_label(
    draw: ImageDraw.ImageDraw,
    label: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: float,
    *,
    max_lines: int,
) -> list[str]:
    words = label.split() or ["?"]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bounds = draw.textbbox((0, 0), candidate, font=font)
        if current and bounds[2] - bounds[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) <= max_lines:
        return lines
    visible = lines[:max_lines]
    last = f"{visible[-1]}…"
    while len(last) > 1:
        bounds = draw.textbbox((0, 0), last, font=font)
        if bounds[2] - bounds[0] <= max_width:
            break
        last = f"{last[:-2]}…"
    visible[-1] = last
    return visible


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


def _dashed_rectangle(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    colour: str,
) -> None:
    left, top, right, bottom = box
    inset = 8
    left += inset
    top += inset
    right -= inset
    bottom -= inset
    dash = 9
    gap = 7
    for start in range(int(left), int(right), dash + gap):
        draw.line((start, top, min(start + dash, right), top), fill=colour, width=2)
        draw.line(
            (start, bottom, min(start + dash, right), bottom),
            fill=colour,
            width=2,
        )
    for start in range(int(top), int(bottom), dash + gap):
        draw.line((left, start, left, min(start + dash, bottom)), fill=colour, width=2)
        draw.line(
            (right, start, right, min(start + dash, bottom)),
            fill=colour,
            width=2,
        )


def _font(
    size: int, *, heading: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ("georgiab.ttf", "DejaVuSerif-Bold.ttf", "timesbd.ttf")
        if heading
        else ("georgia.ttf", "DejaVuSerif.ttf", "arial.ttf")
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _png(image: Image.Image) -> BytesIO:
    output = BytesIO()
    image.save(output, "PNG", optimize=True)
    output.seek(0)
    return output
