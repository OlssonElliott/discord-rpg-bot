"""Room drawing, fog, labels, and occupant markers for dungeon maps."""

from random import Random

from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFont

from ..world.dungeon import KnowledgeState, PlayerMap
from .assets import _loaded_room_art


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


def _draw_rooms(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    view: PlayerMap,
    positions: dict[str, tuple[float, float, float, float]],
    focus_distances: dict[str, int],
    room_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    mystery_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    marker_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """Draw all visible rooms, labels, occupant markers, and room fog."""
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
