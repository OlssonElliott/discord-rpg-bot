"""Render player-safe room memories as complete dark-fantasy cards."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .dungeon import FocusedRoomView, KnowledgeState


ROOM_PANEL_PATH = Path(__file__).resolve().parents[1] / "assets" / "map" / "panel.png"
PANEL_SIZE = (1448, 1086)
SCENE_VIEWPORT = (170, 130, 1278, 596)
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
    rendered = card.convert("RGB")
    try:
        rendered.save(output, format="WEBP", lossless=True, method=6)
        output.seek(0)
    finally:
        rendered.close()
        card.close()
    return output


def _place_scene(card: Image.Image, scene_path: Path) -> bool:
    if not scene_path.is_file():
        return False
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
        card.paste(scene, SCENE_VIEWPORT[:2])
    finally:
        scene.close()
    return True


def _draw_scene_placeholder(
    draw: ImageDraw.ImageDraw,
    *,
    known: bool,
    unavailable: bool,
) -> None:
    left, top, right, bottom = SCENE_VIEWPORT
    draw.rectangle((left, top, right, bottom), fill="#0c0d0e")
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
    status_font = _font(27, heading=True)
    title_font = _font(52, heading=True)
    body_font = _font(29)
    heading_font = _font(23, heading=True)
    list_font = _font(27)

    draw.text((left, top), status, font=status_font, fill="#b79354")
    if not known and not is_current:
        status_box = draw.textbbox((left, top), status, font=status_font)
        draw.text(
            (status_box[2] + 22, top + 2),
            "·  VISITED",
            font=_font(23, heading=True),
            fill="#80745f",
        )

    title = f"? {view.name}" if known else view.name
    title_lines = _wrap_text(draw, title, title_font, right - left, max_lines=2)
    title_y = top + 42
    for line in title_lines:
        draw.text((left, title_y), line, font=title_font, fill="#eee0c0")
        title_y += 50

    description = (
        "You have not personally visited this place."
        if known
        else view.description or "No description has been recorded."
    )
    description_top = max(top + 115, title_y + 3)
    description_lines = _wrap_text(
        draw, description, body_font, right - left, max_lines=2
    )
    for line in description_lines:
        draw.text((left, description_top), line, font=body_font, fill="#bdb19c")
        description_top += 32

    if known:
        return

    section_top = top + 215
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
    column_width = (right - left) / len(sections)
    for index, (heading, values) in enumerate(sections):
        column_left = left + index * column_width
        draw.text(
            (column_left, section_top),
            heading,
            font=heading_font,
            fill="#a9864c",
        )
        value_y = section_top + 34
        for value in _summarize(values, limit=1):
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
