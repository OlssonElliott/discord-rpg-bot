"""Pillow renderer for already-filtered player dungeon maps."""

from collections import Counter
from io import BytesIO
from random import Random

from PIL import Image, ImageDraw, ImageFont

from .dungeon import KnowledgeState, PlayerMap


MAP_WIDTH = 1600
MAP_HEIGHT = 1000
PADDING = 80
MIN_ROOM_WIDTH = 250
MIN_ROOM_HEIGHT = 160


def render_player_map(view: PlayerMap) -> BytesIO:
    """Render only the rooms and connections contained in ``view``."""
    image = Image.new("RGB", (MAP_WIDTH, MAP_HEIGHT), "#15120f")
    draw = ImageDraw.Draw(image)
    _dark_fantasy_backdrop(draw)
    title_font = _font(42, heading=True)
    room_font = _font(30, heading=True)
    unknown_room_font = _font(27, heading=True)
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

    positions = _layout(view)
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
            start = _edge_point(source, target, boxes[connection.from_room_id])
            end = _edge_point(target, source, boxes[connection.to_room_id])
            draw.line((*start, *end), fill="#080706", width=13)
            draw.line((*start, *end), fill="#645338", width=6)
            draw.line((*start, *end), fill="#9a8051", width=2)
            midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            draw.ellipse(
                (midpoint[0] - 8, midpoint[1] - 8, midpoint[0] + 8, midpoint[1] + 8),
                fill="#655239",
                outline="#c4a66b",
                width=2,
            )
            draw.ellipse(
                (midpoint[0] - 3, midpoint[1] - 3, midpoint[0] + 3, midpoint[1] + 3),
                fill="#dbc38b",
            )
        else:
            local_id = (
                connection.from_room_id
                if connection.from_room_id in centers
                else connection.to_room_id
            )
            local = centers.get(local_id)
            if local:
                endpoint = (local[0] + 105, local[1] + 80)
                draw.line((*local, *endpoint), fill="#090806", width=15)
                draw.line((*local, *endpoint), fill="#75603e", width=6)
                other_floor_id = (
                    connection.to_floor_id
                    if local_id == connection.from_room_id
                    else connection.from_floor_id
                )
                connection_name = connection.connection_type.value.replace("_", " ")
                label = f"{connection_name} -> {other_floor_id}"
                draw.text(endpoint, label, fill="#c7b58e", font=small_font)

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
        draw.rounded_rectangle(
            (left + 10, top + 12, left + width + 10, top + height + 12),
            radius=18,
            fill="#090806",
        )
        draw.rounded_rectangle(box, radius=18, fill=fill)
        _room_texture(draw, box, room.id, visited)
        draw.rounded_rectangle(
            box, radius=18, outline=outline, width=border_width
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
            question_box = draw.textbbox((0, 0), "?", font=mystery_font)
            draw.text(
                (
                    left + width - (question_box[2] - question_box[0]) - 22,
                    top + 10,
                ),
                "?",
                fill="#302c27",
                font=mystery_font,
            )
        _draw_room_label(
            draw,
            room.display_name,
            box,
            unknown_room_font if not visited else room_font,
            "#ece0c6" if visited else "#9b9282",
            reserve_markers=bool(room.visible_characters),
        )
        if room.visible_characters:
            _player_markers(draw, box, room.visible_characters, marker_font)

    return _png(image)


def _dark_fantasy_backdrop(draw: ImageDraw.ImageDraw) -> None:
    """Paint a restrained stone-and-brass frame without external assets."""
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
    coordinate_counts = Counter((room.x, room.y) for room in view.rooms)
    raw: dict[str, tuple[float, float, float, float]] = {}
    for index, room in enumerate(view.rooms):
        x, y = room.x, room.y
        if coordinate_counts[(x, y)] > 1:
            x += (index % 4) * 180
            y += (index // 4) * 125
        raw[room.id] = (x, y, max(110, room.width * 85), max(72, room.height * 60))

    min_x = min(item[0] for item in raw.values())
    min_y = min(item[1] for item in raw.values())
    max_x = max(item[0] + item[2] for item in raw.values())
    max_y = max(item[1] + item[3] for item in raw.values())
    viewport_left = PADDING
    viewport_top = 145
    viewport_right = MAP_WIDTH - PADDING
    viewport_bottom = MAP_HEIGHT - PADDING
    available_width = viewport_right - viewport_left
    available_height = viewport_bottom - viewport_top
    scale = min(
        3.0,
        available_width / max(1, max_x - min_x),
        available_height / max(1, max_y - min_y),
    )
    # A little breathing room lets the viewport favour the current room instead
    # of pinning an edge room against the canvas just to maximize raw scale.
    if view.current_room_id in raw:
        scale *= 0.84

    current = raw.get(view.current_room_id or "")
    focused = raw.get(view.focused_room_id or "")
    anchor = current or focused
    if (
        current is not None
        and focused is not None
        and view.focused_room_id != view.current_room_id
    ):
        current_center = _room_center(current)
        focused_center = _room_center(focused)
        anchor_center = (
            current_center[0] * 0.72 + focused_center[0] * 0.28,
            current_center[1] * 0.72 + focused_center[1] * 0.28,
        )
    elif anchor is not None:
        anchor_center = _room_center(anchor)
    else:
        anchor_center = ((min_x + max_x) / 2, (min_y + max_y) / 2)

    viewport_center = (
        (viewport_left + viewport_right) / 2,
        (viewport_top + viewport_bottom) / 2,
    )
    desired_offset_x = viewport_center[0] - anchor_center[0] * scale
    desired_offset_y = viewport_center[1] - anchor_center[1] * scale
    offset_x = _bounded_offset(
        desired_offset_x,
        viewport_left - min_x * scale,
        viewport_right - max_x * scale,
    )
    offset_y = _bounded_offset(
        desired_offset_y,
        viewport_top - min_y * scale,
        viewport_bottom - max_y * scale,
    )
    positioned = {}
    for room_id, (x, y, width, height) in raw.items():
        rendered_width = max(MIN_ROOM_WIDTH, width * scale)
        rendered_height = max(MIN_ROOM_HEIGHT, height * scale)
        center_x = offset_x + (x + width / 2) * scale
        center_y = offset_y + (y + height / 2) * scale
        left = max(
            viewport_left,
            min(center_x - rendered_width / 2, viewport_right - rendered_width),
        )
        top = max(
            viewport_top,
            min(center_y - rendered_height / 2, viewport_bottom - rendered_height),
        )
        positioned[room_id] = (left, top, rendered_width, rendered_height)
    return positioned


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
    *,
    reserve_markers: bool,
) -> None:
    """Wrap by measured width and vertically balance the map label."""
    left, top, right, bottom = box
    lines = _wrap_label(draw, label, font, right - left - 42, max_lines=3)
    line_height = max(28, draw.textbbox((0, 0), "Ag", font=font)[3] + 5)
    label_bottom = bottom - (70 if reserve_markers else 22)
    available_height = max(line_height, label_bottom - (top + 22))
    text_height = line_height * len(lines)
    text_y = top + 22 + max(0, (available_height - text_height) / 2)
    for line in lines:
        text_box = draw.textbbox((0, 0), line, font=font)
        text_width = text_box[2] - text_box[0]
        draw.text(
            (left + (right - left - text_width) / 2, text_y),
            line,
            fill=colour,
            font=font,
            stroke_width=1,
            stroke_fill="#17130f",
        )
        text_y += line_height


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


def _room_center(room: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, width, height = room
    return x + width / 2, y + height / 2


def _bounded_offset(desired: float, fit_at_start: float, fit_at_end: float) -> float:
    """Prefer the anchor position while keeping the known map inside the viewport."""
    lower = min(fit_at_start, fit_at_end)
    upper = max(fit_at_start, fit_at_end)
    return max(lower, min(desired, upper))


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
