"""Compose a room memory image inside the supplied dark-fantasy panel."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


ROOM_PANEL_PATH = Path(__file__).resolve().parents[1] / "assets" / "map" / "panel.png"
PANEL_CROP = (0, 0, 1448, 660)
SCENE_OPENING = (135, 128, 1313, 596)


@lru_cache(maxsize=1)
def _loaded_room_panel() -> Image.Image | None:
    try:
        with Image.open(ROOM_PANEL_PATH) as source:
            return source.convert("RGBA").crop(PANEL_CROP)
    except (OSError, ValueError):
        return None


def render_room_scene_panel(scene_path: Path) -> BytesIO | None:
    """Frame a readable local scene image, or return ``None`` if unavailable."""
    panel = _loaded_room_panel()
    if panel is None or not scene_path.is_file():
        return None
    try:
        with Image.open(scene_path) as source:
            if getattr(source, "is_animated", False):
                source.seek(0)
            oriented = ImageOps.exif_transpose(source)
            scene = ImageOps.fit(
                oriented.convert("RGB"),
                (
                    SCENE_OPENING[2] - SCENE_OPENING[0],
                    SCENE_OPENING[3] - SCENE_OPENING[1],
                ),
                method=Image.Resampling.LANCZOS,
            )
            scene.load()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return None

    composed = panel.copy()
    composed.paste(scene, SCENE_OPENING[:2])
    output = BytesIO()
    rendered = composed.convert("RGB")
    try:
        rendered.save(output, format="WEBP", quality=90, method=6)
        output.seek(0)
    finally:
        rendered.close()
        scene.close()
        composed.close()
    return output
