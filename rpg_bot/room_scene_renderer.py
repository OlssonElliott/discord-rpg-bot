"""Render player-safe room memories as complete dark-fantasy cards."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .dungeon import FocusedRoomView, KnowledgeState


ROOM_PANEL_PATH = Path(__file__).resolve().parents[1] / "assets" / "map" / "panel.png"
PANEL_SIZE = (1448, 1086)
SCENE_VIEWPORT = (143, 128, 1306, 600)
SCENE_CORNER_RADIUS = 48
INFO_BOUNDS = (150, 670, 1298, 995)


@lru_cache(maxsize=1)
def _loaded_room_panel() -> Image.Image | None:
    try:
        with Image.open(ROOM_PANEL_PATH) as source:
            return source.convert("RGBA").resize(
                PANEL_SIZE, Image.Resampling.LANCZOS
            )
    except (OSError, ValueError):
        return None


def render_room_card(
    view: FocusedRoomView,
    *,
    is_current: bool,
    scene_path: Path | None = None,
) -> BytesIO | None:
    """Render a complete card using only the filtered player room view."""
    panel = _loaded_room_panel()
    if panel is None:
        return None
    card = panel.copy()
    draw = ImageDraw.Draw(card)

    scene_loaded = False
    if view.knowledge_state is KnowledgeState.VISITED and scene_path is not None:
        scene_loaded = _place_scene(card, scene_path)
    if not scene_loaded:
        _draw_scene_placeholder(
            draw,
            known=view.knowledge_state is KnowledgeState.KNOWN,
            unavailable=scene_path is not None,
        )

    _draw_room_information(draw, view, is_current=is_current)
    output = BytesIO()
    try:
        # Keep the panel's transparent outer silhouette. Converting to RGB here
        # produces the black rectangle Discord previously showed around it.
        card.save(output, format="WEBP", lossless=True, method=6)
        output.seek(0)
    finally:
        card.close()
    return output


def _place_scene(card: Image.Image, scene_path: Path) -> bool:
    if not scene_path.is_file():
        return False
    mask: Image.Image | None = None
    try:
        with Image.open(scene_path) as source:
            if getattr(source, "is_animated", False):
                source.seek(0)
            oriented = ImageOps.exif_transpose(source)
            scene = ImageOps.fit(
                oriented.convert("RGB"),
                (
                    SCENE_VIEWPORT[2] - SCENE_VIEWPORT[0],
                    SCENE_VIEWPORT[3] - SCENE_VIEWPORT[1],
                ),
                method=Image.Resampling.LANCZOS,
            )
            scene.load()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return False
    try:
        mask = Image.new("L", scene.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle(
            (0, 0, scene.width - 1, scene.height - 1),
            radius=SCENE_CORNER_RADIUS,
            fill=255,
        )
        card.paste(scene, SCENE_VIEWPORT[:2], mask)
    finally:
        scene.close()
        if mask is not None:
            mask.close()
    return True


def _draw_scene_placeholder(
    draw: ImageDraw.ImageDraw,
    *,
    known: bool,
    unavailable: bool,
) -> None:
    left, top, right, bottom = SCENE_VIEWPORT
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=SCENE_CORNER_RADIUS,
        fill="#0c0d0e",
    )
    for inset in range(0, 150, 10):
        shade = 12 + inset // 15
        draw.rectangle(
            (left + inset, top + inset // 3, right - inset, bottom - inset // 3),
            outline=(shade, shade, max(10, shade - 2)),
            width=2,
        )
    if known:
        label = "VISUAL MEMORY VEILED"
    elif unavailable:
        label = "VISUAL MEMORY UNAVAILABLE"
    else:
        label = "NO VISUAL MEMORY"
    _center_text(
        draw,
        label,
        ((left + right) / 2, (top + bottom) / 2),
        _font(31, heading=True),
        "#8f8067",
    )


def _draw_room_information(
    draw: ImageDraw.ImageDraw,
    view: FocusedRoomView,
    *,
    is_current: bool,
) -> None:
    left, top, right, bottom = INFO_BOUNDS
    known = view.knowledge_state is KnowledgeState.KNOWN
    status = (
        "KNOWN LOCATION"
        if known
        else "CURRENT ROOM"
        if is_current
        else "INSPECTED ROOM"
    )
    if not known and not is_current:
        status = f"{status} · VISITED"
    status_font = _font(27, heading=True)
    body_font = _font(27)
    heading_font = _font(23, heading=True)
    list_font = _font(25)

    status_y = top + 5
    draw.text((left, status_y), status, font=status_font, fill="#b79354")
    status_box = draw.textbbox((left, status_y), status, font=status_font)

    title = f"? {view.name}" if known else view.name
    title_left = status_box[2] + 34
    title_text, title_font = _fit_heading(
        draw,
        title,
        max_width=right - title_left,
    )
    draw.text(
        (title_left, top - 3),
        title_text,
        font=title_font,
        fill="#eee0c0",
    )

    description = (
        "You have not personally visited this place."
        if known
        else view.description or "No description has been recorded."
    )
    content_top = top + 88
    gutter = 48
    left_width = (right - left - gutter) * 0.5
    right_left = left + left_width + gutter
    draw.text(
        (left, content_top),
        "DESCRIPTION",
        font=heading_font,
        fill="#a9864c",
    )
    description_top = content_top + 38
    description_lines = _wrap_text(
        draw,
        description,
        body_font,
        left_width,
        max_lines=5,
    )
    for line in description_lines:
        draw.text((left, description_top), line, font=body_font, fill="#bdb19c")
        description_top += 34

    if known:
        return

    available_sections = [
        ("CHARACTERS", view.visible_characters),
        ("VISIBLE", view.visible_entities),
        ("ITEMS", view.visible_items),
    ]
    sections = [(heading, values) for heading, values in available_sections if values]
    if not sections:
        if not is_current:
            return
        sections = [("CHARACTERS", ("None",)), ("ITEMS", ("None",))]
    right_width = right - right_left
    column_width = right_width / len(sections)
    for index, (heading, values) in enumerate(sections):
        column_left = right_left + index * column_width
        draw.text(
            (column_left, content_top),
            heading,
            font=heading_font,
            fill="#a9864c",
        )
        value_y = content_top + 38
        for value in _summarize(values, limit=3):
            if value_y > bottom - 25:
                break
            lines = _wrap_text(
                draw,
                value,
                list_font,
                column_width - 36,
                max_lines=1,
            )
            draw.text(
                (column_left, value_y),
                lines[0],
                font=list_font,
                fill="#ddd2bd",
            )
            value_y += 33


def _fit_heading(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: float,
) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    """Fit a room name on the single status row without touching the frame."""
    for size in range(42, 27, -2):
        font = _font(size, heading=True)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return text, font
    font = _font(28, heading=True)
    fitted = text
    while len(fitted) > 1:
        candidate = f"{fitted.rstrip()}…"
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            return candidate, font
        fitted = fitted[:-1]
    return "…", font


def _summarize(values: tuple[str, ...], *, limit: int) -> tuple[str, ...]:
    visible = values[:limit]
    remaining = len(values) - len(visible)
    return visible + ((f"+ {remaining} more",) if remaining else ())


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: float,
    *,
    max_lines: int,
) -> list[str]:
    words = text.split() or ["—"]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), candidate, font=font)
        if current and box[2] - box[0] > max_width:
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
        box = draw.textbbox((0, 0), last, font=font)
        if box[2] - box[0] <= max_width:
            break
        last = f"{last[:-2]}…"
    visible[-1] = last
    return visible


def _center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center: tuple[float, float],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    colour: str,
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (
            center[0] - (box[2] - box[0]) / 2 - box[0],
            center[1] - (box[3] - box[1]) / 2 - box[1],
        ),
        text,
        font=font,
        fill=colour,
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
