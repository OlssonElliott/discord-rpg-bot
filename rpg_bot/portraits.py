"""Validation and local storage for character portraits."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_PORTRAIT_BYTES = 5 * 1024 * 1024
MAX_PORTRAIT_PIXELS = 25_000_000
PORTRAIT_SIZE = (256, 256)
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
DEFAULT_PORTRAIT_ROOT = (
    Path(__file__).resolve().parent.parent / "assets" / "character_portraits" / "default"
)
DEFAULT_DM_PORTRAIT_KEY = "default/dungeon_master.png"
GENDERED_DEFAULT_RACES = {"Human", "Dwarf", "Halfling", "Elf"}
DEFAULT_PORTRAIT_FILES = {
    "Dryad": "dryad.png",
    "Faun": "faun.png",
    "Gnoll": "gnoll.png",
    "Goblin": "goblin.png",
    "Hagspawn": "hagspawn.png",
    "Lizardman": "lizardman.png",
    "Minotaur": "minotaur.png",
    "Orc": "orc.png",
    "Revenant": "revenant.png",
    "Swarmling": "swarmling.png",
    "Troll": "troll.png",
}


class InvalidPortraitError(ValueError):
    pass


class CharacterPortraitStore:
    def __init__(
        self,
        root: str | Path = "data/characters",
        *,
        default_root: str | Path = DEFAULT_PORTRAIT_ROOT,
    ) -> None:
        self.root = Path(root)
        self.default_root = Path(default_root)

    def save(self, character_id: int, content: bytes) -> str:
        return self._save(f"{character_id}/portrait-{uuid4().hex}.webp", content)

    def save_dm(self, discord_user_id: int, content: bytes) -> str:
        return self._save(
            f"dm/{discord_user_id}/portrait-{uuid4().hex}.webp", content
        )

    def _save(self, key: str, content: bytes) -> str:
        if len(content) > MAX_PORTRAIT_BYTES:
            raise InvalidPortraitError("Portraits may be at most 5 MB.")
        if not content:
            raise InvalidPortraitError("The uploaded portrait is empty.")

        try:
            with Image.open(BytesIO(content)) as source:
                if source.format not in ALLOWED_FORMATS:
                    raise InvalidPortraitError(
                        "Use a PNG, JPEG, or WebP image for the portrait."
                    )
                if source.width * source.height > MAX_PORTRAIT_PIXELS:
                    raise InvalidPortraitError("The portrait has too many pixels.")
                if getattr(source, "is_animated", False):
                    source.seek(0)
                oriented = ImageOps.exif_transpose(source)
                mode = "RGBA" if "A" in oriented.getbands() else "RGB"
                portrait = ImageOps.fit(
                    oriented.convert(mode),
                    PORTRAIT_SIZE,
                    method=Image.Resampling.LANCZOS,
                )
                portrait.load()
        except InvalidPortraitError:
            raise
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
            raise InvalidPortraitError(
                "Discord could not read that image. Use a valid PNG, JPEG, or WebP file."
            ) from error

        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            portrait.save(temporary, format="WEBP", quality=88, method=6)
            temporary.replace(target)
        finally:
            portrait.close()
            temporary.unlink(missing_ok=True)
        return key

    def path_for(self, key: str | None) -> Path | None:
        if key and key.startswith("default/"):
            filename = key.removeprefix("default/")
            if filename not in set(default_portrait_filenames()):
                return None
            path = self.default_root / filename
            return path if path.is_file() else None
        if key is None or not re.fullmatch(
            r"(?:[1-9][0-9]*|dm/[1-9][0-9]*)/"
            r"portrait(?:-[0-9a-f]{32})?\.webp",
            key,
        ):
            return None
        path = self.root / Path(key)
        return path if path.is_file() else None

    def remove(self, key: str | None) -> None:
        if is_default_portrait_key(key):
            return
        path = self.path_for(key)
        if path is not None:
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass


def default_portrait_filenames() -> tuple[str, ...]:
    gendered = tuple(
        f"{race.casefold()}_{gender}.png"
        for race in sorted(GENDERED_DEFAULT_RACES)
        for gender in ("male", "female")
    )
    return gendered + tuple(DEFAULT_PORTRAIT_FILES.values()) + ("dungeon_master.png",)


def default_portrait_key(race: str | None, gender: str | None) -> str | None:
    if race in GENDERED_DEFAULT_RACES and gender in {"Male", "Female"}:
        return f"default/{race.casefold()}_{gender.casefold()}.png"
    filename = DEFAULT_PORTRAIT_FILES.get(race or "")
    return f"default/{filename}" if filename else None


def is_default_portrait_key(key: str | None) -> bool:
    return bool(key and key.startswith("default/"))
