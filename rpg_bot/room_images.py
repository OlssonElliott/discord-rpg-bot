"""Validated local storage for persistent dungeon room images."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_ROOM_IMAGE_BYTES = 8 * 1024 * 1024
MAX_ROOM_IMAGE_PIXELS = 40_000_000
MAX_ROOM_IMAGE_SIZE = (1920, 1440)
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


class InvalidRoomImageError(ValueError):
    pass


class RoomImageStore:
    """Store normalized WebP room images behind opaque generated keys."""

    def __init__(self, root: str | Path = "data/room_images") -> None:
        self.root = Path(root)

    def save(
        self,
        content: bytes,
        content_type: str,
        original_filename: str | None = None,
    ) -> str:
        declared_type = content_type.partition(";")[0].strip().casefold()
        declared_format = ALLOWED_IMAGE_MIME_TYPES.get(declared_type)
        if declared_format is None:
            raise InvalidRoomImageError("Use a PNG, JPEG, or WebP room image.")
        if original_filename:
            extension_format = ALLOWED_IMAGE_EXTENSIONS.get(
                Path(original_filename).suffix.casefold()
            )
            if extension_format is None:
                raise InvalidRoomImageError(
                    "The room image filename must end in .png, .jpg, .jpeg, or .webp."
                )
            if extension_format != declared_format:
                raise InvalidRoomImageError(
                    "The room image extension does not match its content type."
                )
        if not content:
            raise InvalidRoomImageError("The uploaded room image is empty.")
        if len(content) > MAX_ROOM_IMAGE_BYTES:
            raise InvalidRoomImageError("Room images may be at most 8 MB.")

        try:
            with Image.open(BytesIO(content)) as source:
                if source.format not in ALLOWED_IMAGE_FORMATS:
                    raise InvalidRoomImageError(
                        "Use a PNG, JPEG, or WebP room image."
                    )
                if source.format != declared_format:
                    raise InvalidRoomImageError(
                        "The uploaded file does not match its image content type."
                    )
                if source.width * source.height > MAX_ROOM_IMAGE_PIXELS:
                    raise InvalidRoomImageError("The room image has too many pixels.")
                if getattr(source, "is_animated", False):
                    source.seek(0)
                oriented = ImageOps.exif_transpose(source)
                mode = "RGBA" if "A" in oriented.getbands() else "RGB"
                normalized = oriented.convert(mode)
                normalized.thumbnail(MAX_ROOM_IMAGE_SIZE, Image.Resampling.LANCZOS)
                normalized.load()
        except InvalidRoomImageError:
            raise
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
            raise InvalidRoomImageError(
                "The upload is not a readable PNG, JPEG, or WebP image."
            ) from error

        key = f"{uuid4().hex}.webp"
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            normalized.save(temporary, format="WEBP", quality=90, method=6)
            temporary.replace(target)
        finally:
            normalized.close()
            temporary.unlink(missing_ok=True)
        return key

    def path_for(self, key: str | None) -> Path | None:
        if key is None or not re.fullmatch(r"[0-9a-f]{32}\.webp", key):
            return None
        path = self.root / key
        return path if path.is_file() else None

    def remove(self, key: str | None) -> None:
        path = self.path_for(key)
        if path is not None:
            path.unlink(missing_ok=True)
