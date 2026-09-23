"""Packaged artwork and cached asset loading for the dungeon map renderer."""

from functools import lru_cache
from pathlib import Path

from PIL import Image


MAP_WIDTH = 1600
MAP_HEIGHT = 1000
MAP_BACKGROUND_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "map" / "background.png"
)
ROOM_ART_PATH = Path(__file__).resolve().parents[2] / "assets" / "map" / "room.png"
DOOR_ART_PATH = Path(__file__).resolve().parents[2] / "assets" / "map" / "door.png"
OPEN_DOOR_ART_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "map" / "door-open.png"
)
HALLWAY_ART_PATH = Path(__file__).resolve().parents[2] / "assets" / "map" / "hallway.png"
LOCKED_ART_PATH = Path(__file__).resolve().parents[2] / "assets" / "map" / "lock.png"
UNLOCKED_ART_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "map" / "lock-unlocked.png"
)
BROKEN_LOCK_ART_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "map" / "lock-broken.png"
)
TRAP_ART_PATH = Path(__file__).resolve().parents[2] / "assets" / "map" / "trap.png"
TRAP_DISARMED_ART_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "map" / "trap-disarmed.png"
)
TRAP_TRIGGERED_ART_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "map" / "trap-triggered.png"
)
CONNECTION_ART_HEIGHT = 72
LOCK_ART_HEIGHT = 34
LOCK_ART_GAP = 4
TRAP_ART_HEIGHT = LOCK_ART_HEIGHT
TRAP_ART_GAP = LOCK_ART_GAP


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


@lru_cache(maxsize=1)
def _loaded_door_art() -> Image.Image | None:
    """Load the door marker, crop transparent padding, and keep it upright."""
    return _load_map_marker_art(DOOR_ART_PATH, CONNECTION_ART_HEIGHT)


@lru_cache(maxsize=1)
def _loaded_open_door_art() -> Image.Image | None:
    """Load the open door at the same visual height as the closed door."""
    return _load_map_marker_art(OPEN_DOOR_ART_PATH, CONNECTION_ART_HEIGHT)


@lru_cache(maxsize=1)
def _loaded_hallway_art() -> Image.Image | None:
    """Load the hallway marker at the same visual height as the door."""
    return _load_map_marker_art(HALLWAY_ART_PATH, CONNECTION_ART_HEIGHT)


@lru_cache(maxsize=1)
def _loaded_locked_art() -> Image.Image | None:
    return _load_map_marker_art(LOCKED_ART_PATH, LOCK_ART_HEIGHT)


@lru_cache(maxsize=1)
def _loaded_unlocked_art() -> Image.Image | None:
    return _load_map_marker_art(UNLOCKED_ART_PATH, LOCK_ART_HEIGHT)


@lru_cache(maxsize=1)
def _loaded_broken_lock_art() -> Image.Image | None:
    return _load_map_marker_art(BROKEN_LOCK_ART_PATH, LOCK_ART_HEIGHT)


@lru_cache(maxsize=1)
def _loaded_trap_art() -> Image.Image | None:
    return _load_map_marker_art(TRAP_ART_PATH, TRAP_ART_HEIGHT)


@lru_cache(maxsize=1)
def _loaded_disarmed_trap_art() -> Image.Image | None:
    return _load_map_marker_art(TRAP_DISARMED_ART_PATH, TRAP_ART_HEIGHT)


@lru_cache(maxsize=1)
def _loaded_triggered_trap_art() -> Image.Image | None:
    return _load_map_marker_art(TRAP_TRIGGERED_ART_PATH, TRAP_ART_HEIGHT)


@lru_cache(maxsize=1)
def _door_visual_anchor() -> tuple[float, float] | None:
    """Return the alpha-weighted center of the visible door motif."""
    door = _loaded_door_art()
    if door is None:
        return None
    alpha = door.getchannel("A")
    values = tuple(alpha.getdata())
    total_alpha = sum(values)
    if not total_alpha:
        return ((door.width - 1) / 2, (door.height - 1) / 2)
    return (
        sum((index % door.width) * value for index, value in enumerate(values))
        / total_alpha,
        sum((index // door.width) * value for index, value in enumerate(values))
        / total_alpha,
    )


@lru_cache(maxsize=1)
def _open_door_visual_anchor() -> tuple[float, float] | None:
    """Return the alpha-weighted center of the open-door motif."""
    door = _loaded_open_door_art()
    if door is None:
        return None
    alpha = door.getchannel("A")
    values = tuple(alpha.getdata())
    total_alpha = sum(values)
    if not total_alpha:
        return ((door.width - 1) / 2, (door.height - 1) / 2)
    return (
        sum((index % door.width) * value for index, value in enumerate(values))
        / total_alpha,
        sum((index // door.width) * value for index, value in enumerate(values))
        / total_alpha,
    )


def _load_map_marker_art(path: Path, target_height: int) -> Image.Image | None:
    """Crop transparent padding and uniformly size map-marker artwork."""
    try:
        with Image.open(path) as source:
            artwork = source.convert("RGBA")
        visible_bounds = artwork.getchannel("A").point(
            lambda value: 255 if value >= 16 else 0
        ).getbbox()
        if visible_bounds is None:
            return None
        artwork = artwork.crop(visible_bounds)
        target_width = max(
            1, round(target_height * artwork.width / artwork.height)
        )
        return artwork.resize(
            (target_width, target_height), Image.Resampling.LANCZOS
        )
    except (OSError, ValueError):
        return None
