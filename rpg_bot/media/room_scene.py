"""Render player-safe room memories as complete dark-fantasy cards."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageFilter,
    ImageFont,
    ImageOps,
    UnidentifiedImageError,
)

from ..world.dungeon import FocusedRoomView, KnowledgeState


ROOM_PANEL_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "map" / "panel-square.png"
)
PANEL_SIZE = (1448, 1086)
SCENE_APERTURE_BOUNDS = (118, 108, 1330, 629)
SCENE_UNDERLAY = 18
SCENE_LAYER_BOUNDS = (
    SCENE_APERTURE_BOUNDS[0] - SCENE_UNDERLAY,
    SCENE_APERTURE_BOUNDS[1] - SCENE_UNDERLAY,
    SCENE_APERTURE_BOUNDS[2] + SCENE_UNDERLAY,
    SCENE_APERTURE_BOUNDS[3] + SCENE_UNDERLAY,
)
SCENE_MASK_SCALE = 4
INFO_BOUNDS = (150, 670, 1298, 995)
INFO_COLUMN_PROPORTIONS = (0.36, 0.22, 0.42)
INFO_COLUMN_GAP = 28


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
        scene_loaded = _place_scene(card, panel, scene_path)
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


def _place_scene(card: Image.Image, panel: Image.Image, scene_path: Path) -> bool:
    if not scene_path.is_file():
        return False
    scene_layer: Image.Image | None = None
    scene_mask: Image.Image | None = None
    frame_mask: Image.Image | None = None
    try:
        with Image.open(scene_path) as source:
            if getattr(source, "is_animated", False):
                source.seek(0)
            oriented = ImageOps.exif_transpose(source)
            scene = ImageOps.fit(
                oriented.convert("RGB"),
                (
                    SCENE_LAYER_BOUNDS[2] - SCENE_LAYER_BOUNDS[0],
                    SCENE_LAYER_BOUNDS[3] - SCENE_LAYER_BOUNDS[1],
                ),
                method=Image.Resampling.LANCZOS,
            )
            scene.load()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return False
    try:
        # Build the scene independently, crop it to the upper region, then put
        # the original panel back above it with only its aperture removed. The
        # scene therefore continues beneath the ornate frame by 18 pixels.
        scene_layer = Image.new("RGBA", PANEL_SIZE, (0, 0, 0, 0))
        scene_layer.paste(scene, SCENE_LAYER_BOUNDS[:2])
        scene_mask = _scene_aperture_mask()
        card.paste(scene_layer, (0, 0), scene_mask)

        # Restore every pixel outside the panel-specific opening. This places
        # the ornate corners and both centre ornaments above the oversized
        # scene without approximating them with broad, visible polygons.
        frame_mask = ImageOps.invert(scene_mask)
        card.paste(panel, (0, 0), frame_mask)
        _draw_inner_scene_shadow(card, scene_mask)
    finally:
        scene.close()
        for image in (scene_layer, scene_mask, frame_mask):
            if image is not None:
                image.close()
    return True


def _scene_aperture_mask() -> Image.Image:
    """Return an antialiased rectangular mask for the clean scene opening."""
    scale = SCENE_MASK_SCALE
    mask = Image.new("L", (PANEL_SIZE[0] * scale, PANEL_SIZE[1] * scale), 0)
    ImageDraw.Draw(mask).rectangle(
        tuple(value * scale for value in SCENE_APERTURE_BOUNDS),
        fill=255,
    )
    resized = mask.resize(PANEL_SIZE, Image.Resampling.LANCZOS)
    mask.close()
    return resized


def _draw_inner_scene_shadow(card: Image.Image, aperture_mask: Image.Image) -> None:
    """Add a very small inner lip that follows the custom aperture."""
    shadow = Image.new("RGBA", PANEL_SIZE, (0, 0, 0, 0))
    eroded: Image.Image | None = None
    edge: Image.Image | None = None
    try:
        eroded = aperture_mask.filter(ImageFilter.MinFilter(5))
        edge = ImageChops.subtract(aperture_mask, eroded).point(
            lambda value: value * 44 // 255
        )
        shadow.putalpha(edge)
        card.alpha_composite(shadow)
    finally:
        shadow.close()
        if eroded is not None:
            eroded.close()
        if edge is not None:
            edge.close()


def _draw_scene_placeholder(
    draw: ImageDraw.ImageDraw,
    *,
    known: bool,
    unavailable: bool,
) -> None:
    left, top, right, bottom = SCENE_APERTURE_BOUNDS
    aperture_mask = _scene_aperture_mask()
    try:
        draw.bitmap((0, 0), aperture_mask, fill="#0c0d0e")
    finally:
        aperture_mask.close()
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
    body_font = _font(25)
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
    usable_width = right - left - (2 * INFO_COLUMN_GAP)
    description_width = usable_width * INFO_COLUMN_PROPORTIONS[0]
    characters_width = usable_width * INFO_COLUMN_PROPORTIONS[1]
    characters_left = left + description_width + INFO_COLUMN_GAP
    items_left = characters_left + characters_width + INFO_COLUMN_GAP
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
        description_width,
        max_lines=6,
    )
    for line in description_lines:
        draw.text((left, description_top), line, font=body_font, fill="#bdb19c")
        description_top += 32

    if known:
        return

    character_values = view.visible_characters + view.visible_entities
    if is_current:
        character_values = character_values or ("None",)
        item_values = view.visible_items or ("None",)
    else:
        item_values = view.visible_items
    sections = (
        ("CHARACTERS", character_values, characters_left, characters_width),
        (
            "ITEMS",
            item_values,
            items_left,
            usable_width * INFO_COLUMN_PROPORTIONS[2],
        ),
    )
    for heading, values, column_left, column_width in sections:
        if not values:
            continue
        draw.text(
            (column_left, content_top),
            heading,
            font=heading_font,
            fill="#a9864c",
        )
        value_y = content_top + 38
        lines = _list_lines(
            draw,
            values,
            list_font,
            column_width - 16,
            max_lines=5,
        )
        for line in lines:
            draw.text(
                (column_left, value_y),
                line,
                font=list_font,
                fill="#ddd2bd",
            )
            value_y += 32


def _list_lines(
    draw: ImageDraw.ImageDraw,
    values: tuple[str, ...],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: float,
    *,
    max_lines: int,
) -> tuple[str, ...]:
    """Lay out list values vertically, wrapping names before truncating them."""
    summarized = _summarize(values, limit=3)
    lines: list[str] = []
    for index, value in enumerate(summarized):
        lines_left = max_lines - len(lines)
        if lines_left <= 0:
            break
        remaining_values = len(summarized) - index - 1
        value_lines = min(2, max(1, lines_left - remaining_values))
        lines.extend(
            _wrap_text(
                draw,
                value,
                font,
                max_width,
                max_lines=value_lines,
            )
        )
    return tuple(lines[:max_lines])


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
