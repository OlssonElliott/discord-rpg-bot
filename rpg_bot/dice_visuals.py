"""Tint and cache neutral dice GIFs without changing their animation."""

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import re
import threading

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageSequence

from .dice_assets import (
    DEFAULT_DICE_THEME,
    DiceAsset,
    DiceAssetLayout,
    normalize_dice_theme,
)


LOGGER = logging.getLogger(__name__)

DEFAULT_DICE_COLOR = "#C89B3C"
DEFAULT_DICE_EDGE_COLOR = "#303030"
DEFAULT_DICE_NUMBER_COLOR = "#101010"
SUPPORTED_VISUAL_DICE = frozenset((4, 6, 8, 10, 12, 20))
MAX_VISUAL_DICE_COUNT = 10
RESULT_IMAGE_SIZE = 160
GROUP_RESULT_TILE_SIZE = 160
MULTI_ANIMATION_MAX_WIDTH = 640
DICE_GROUP_CACHE_VERSION = "v13"
DISCORD_DARK_MATTE = (43, 45, 49)
_HEX_COLOR = re.compile(r"#?(?P<rgb>[0-9a-fA-F]{6})")


class InvalidDiceColorError(ValueError):
    """Raised when a dice color is not a six-digit RGB hexadecimal value."""


def normalize_dice_color(color: str) -> str:
    """Return an RGB color in canonical ``#RRGGBB`` form."""
    match = _HEX_COLOR.fullmatch(color.strip())
    if match is None:
        raise InvalidDiceColorError(
            "Use a six-digit hexadecimal color such as `#7A2EFF`."
        )
    return f"#{match.group('rgb').upper()}"


@dataclass(frozen=True, slots=True)
class RenderedDiceAnimation:
    path: Path
    duration_seconds: float
    result_image_path: Path


class D20AnimationRenderer:
    """Generate a tinted die GIF once, then reuse its disk-cached result.

    The historical class name remains for compatibility, but the renderer supports
    every Rollkeeper visual die through the optional ``sides`` argument.
    """

    def __init__(
        self,
        assets_directory: str | Path | None = None,
        theme: str = DEFAULT_DICE_THEME,
    ) -> None:
        if assets_directory is None:
            assets_directory = (
                Path(__file__).resolve().parent.parent / "assets" / "dice" / "d20"
            )
        self.assets_directory = Path(assets_directory)
        self.theme = normalize_dice_theme(theme)
        self.layout = DiceAssetLayout(self.assets_directory.parent)
        self.master_directory = self.layout.theme_directory(20, self.theme)
        self.cache_directory = self.assets_directory / "cache"
        self._generation_lock = threading.Lock()
        self._logged_warnings: set[str] = set()

    def resolve_master(
        self, natural_result: int, sides: int = 20
    ) -> DiceAsset | None:
        if sides not in SUPPORTED_VISUAL_DICE:
            raise ValueError(f"Visual dice are not available for d{sides}.")
        if not 1 <= natural_result <= sides:
            raise ValueError(
                f"A natural d{sides} result must be between 1 and {sides}."
            )

        candidates = self.layout.master_candidates(sides, natural_result, self.theme)
        selected = candidates[0]
        if selected.path.is_file():
            return selected

        next_location = (
            "trying classic"
            if self.theme != DEFAULT_DICE_THEME
            else "checking the legacy location"
        )
        if selected.path.parent.is_dir():
            self._warn_once(
                str(selected.path),
                "Dice theme '%s' is missing %s; %s.",
                self.theme,
                selected.path.name,
                next_location,
            )
        else:
            self._warn_once(
                str(selected.path.parent),
                "Dice theme '%s' does not exist at %s; %s.",
                self.theme,
                selected.path.parent,
                next_location,
            )

        for candidate in candidates[1:]:
            if not candidate.path.is_file():
                continue
            if candidate.legacy:
                self._warn_once(
                    str(candidate.path),
                    "Using legacy d20 master %s; copy it into themes/classic.",
                    candidate.path,
                )
            elif candidate.theme != self.theme:
                self._warn_once(
                    str(selected.path),
                    "Falling back from dice theme '%s' to '%s' for d%d result %d.",
                    self.theme,
                    candidate.theme,
                    sides,
                    natural_result,
                )
            return candidate

        self._warn_once(
            f"missing:{self.theme}:{natural_result}",
            "No animation asset found for d%d result %d in theme '%s' or classic; "
            "using the instant roll result.",
            sides,
            natural_result,
            self.theme,
        )
        return None

    def render(
        self,
        natural_result: int,
        color: str,
        master_asset: DiceAsset | None = None,
        edge_color: str = DEFAULT_DICE_EDGE_COLOR,
        number_color: str = DEFAULT_DICE_NUMBER_COLOR,
        sides: int = 20,
        glow_color: str | None = None,
    ) -> RenderedDiceAnimation | None:
        """Return a cached/tinted animation, or ``None`` when no master is available."""
        if sides not in SUPPORTED_VISUAL_DICE:
            raise ValueError(f"Visual dice are not available for d{sides}.")
        if not 1 <= natural_result <= sides:
            raise ValueError(
                f"A natural d{sides} result must be between 1 and {sides}."
            )

        normalized_color = normalize_dice_color(color)
        normalized_edge_color = normalize_dice_color(edge_color)
        normalized_number_color = normalize_dice_color(number_color)
        normalized_glow_color = (
            normalize_dice_color(glow_color) if glow_color is not None else None
        )
        resolved_asset = master_asset or self.resolve_master(natural_result, sides)
        if resolved_asset is None:
            return None

        master_path = resolved_asset.path
        edge_mask_path = self.layout.edge_mask_path(resolved_asset)
        number_mask_path = self.layout.number_mask_path(resolved_asset)
        if not edge_mask_path.is_file():
            self._warn_once(
                f"edge-mask:{resolved_asset.theme}",
                "Dice theme '%s' has no edge masks; using the face color for edges.",
                resolved_asset.theme,
            )
        if not number_mask_path.is_file():
            self._warn_once(
                f"number-mask:{resolved_asset.theme}",
                "Dice theme '%s' has no number masks; using its baked number color.",
                resolved_asset.theme,
            )
        cache_path = self.layout.cache_path(
            sides,
            resolved_asset.theme,
            normalized_color,
            natural_result,
            normalized_edge_color,
            normalized_number_color,
        )
        if normalized_glow_color is not None:
            glow_slug = normalized_glow_color.removeprefix("#")
            cache_path = cache_path.with_name(
                f"{cache_path.stem}_glow_v4_{glow_slug}.gif"
            )
        result_image_path = cache_path.with_name(f"{cache_path.stem}_result.png")
        with self._generation_lock:
            newest_source_time = master_path.stat().st_mtime_ns
            if edge_mask_path.is_file():
                newest_source_time = max(
                    newest_source_time, edge_mask_path.stat().st_mtime_ns
                )
            if number_mask_path.is_file():
                newest_source_time = max(
                    newest_source_time, number_mask_path.stat().st_mtime_ns
                )
            if (
                cache_path.is_file()
                and cache_path.stat().st_mtime_ns >= newest_source_time
                and result_image_path.is_file()
                and result_image_path.stat().st_mtime_ns >= newest_source_time
            ):
                duration = self._animation_duration(cache_path)
                if duration is not None:
                    return RenderedDiceAnimation(
                        cache_path, duration, result_image_path
                    )

            return self._generate(
                master_path,
                cache_path,
                normalized_color,
                normalized_edge_color,
                edge_mask_path if edge_mask_path.is_file() else None,
                normalized_number_color,
                number_mask_path if number_mask_path.is_file() else None,
                result_image_path,
                normalized_glow_color,
            )

    def render_many(
        self,
        natural_results: tuple[int, ...],
        color: str,
        master_assets: tuple[DiceAsset, ...] | None = None,
        edge_color: str = DEFAULT_DICE_EDGE_COLOR,
        number_color: str = DEFAULT_DICE_NUMBER_COLOR,
        sides: int = 20,
        primary_index: int | None = None,
        glow_color: str | None = None,
        glow_colors: tuple[str | None, ...] | None = None,
    ) -> RenderedDiceAnimation | None:
        """Compose cached result animations into one synchronized horizontal roll."""
        if not 2 <= len(natural_results) <= MAX_VISUAL_DICE_COUNT:
            raise ValueError(
                f"Visual groups require between 2 and {MAX_VISUAL_DICE_COUNT} dice."
            )
        if sides not in SUPPORTED_VISUAL_DICE:
            raise ValueError(f"Visual dice are not available for d{sides}.")
        if any(not 1 <= result <= sides for result in natural_results):
            raise ValueError(
                f"Natural d{sides} results must be between 1 and {sides}."
            )
        if (
            primary_index is not None
            and not 0 <= primary_index < len(natural_results)
        ):
            raise ValueError("The highlighted die index is outside the result group.")
        if glow_colors is not None and len(glow_colors) != len(natural_results):
            raise ValueError("Each visual die must have one glow color entry.")
        normalized_glow_colors = (
            tuple(
                normalize_dice_color(color) if color is not None else None
                for color in glow_colors
            )
            if glow_colors is not None
            else tuple(
                normalize_dice_color(glow_color) if glow_color is not None else None
                for _ in natural_results
            )
        )

        if master_assets is None:
            resolved = tuple(
                self.resolve_master(result, sides) for result in natural_results
            )
            if any(asset is None for asset in resolved):
                return None
            master_assets = tuple(asset for asset in resolved if asset is not None)
        elif len(master_assets) != len(natural_results):
            raise ValueError("Each visual die result must have one master asset.")

        animations_by_source: dict[tuple[int, Path], RenderedDiceAnimation] = {}
        animations: list[RenderedDiceAnimation] = []
        for result, master_asset in zip(natural_results, master_assets):
            source_key = (result, master_asset.path)
            animation = animations_by_source.get(source_key)
            if animation is None:
                animation = self.render(
                    result,
                    color,
                    master_asset,
                    edge_color,
                    number_color,
                    sides,
                )
                if animation is None:
                    return None
                animations_by_source[source_key] = animation
            animations.append(animation)

        signature_text = "|".join(str(animation.path) for animation in animations)
        signature_text += (
            f"|primary={primary_index}|glows={normalized_glow_colors}"
        )
        signature = hashlib.sha256(signature_text.encode("utf-8")).hexdigest()[:10]
        result_slug = "-".join(str(result) for result in natural_results)
        group_directory = (
            animations[0].path.parent / "groups" / DICE_GROUP_CACHE_VERSION
        )
        cache_path = group_directory / f"d{sides}_{result_slug}_{signature}.gif"
        result_image_path = cache_path.with_name(
            f"{cache_path.stem}_results.png"
        )
        newest_source_time = max(
            path.stat().st_mtime_ns
            for animation in animations
            for path in (animation.path, animation.result_image_path)
        )

        with self._generation_lock:
            if (
                cache_path.is_file()
                and cache_path.stat().st_mtime_ns >= newest_source_time
                and result_image_path.is_file()
                and result_image_path.stat().st_mtime_ns >= newest_source_time
            ):
                duration = self._animation_duration(cache_path)
                if duration is not None:
                    return RenderedDiceAnimation(
                        cache_path, duration, result_image_path
                    )
            return self._generate_group(
                natural_results,
                animations,
                cache_path,
                result_image_path,
                primary_index,
                normalized_glow_colors,
            )

    def _warn_once(self, key: str, message: str, *args: object) -> None:
        if key in self._logged_warnings:
            return
        self._logged_warnings.add(key)
        LOGGER.warning(message, *args)

    def _generate_group(
        self,
        natural_results: tuple[int, ...],
        animations: list[RenderedDiceAnimation],
        cache_path: Path,
        result_image_path: Path,
        primary_index: int | None,
        glow_colors: tuple[str | None, ...],
    ) -> RenderedDiceAnimation | None:
        temporary_path = cache_path.with_suffix(".tmp.gif")
        temporary_result_path = result_image_path.with_name(
            f"{result_image_path.stem}.tmp.png"
        )
        try:
            tile_size = min(
                256,
                MULTI_ANIMATION_MAX_WIDTH // len(animations),
            )
            inner_size = max(1, tile_size - 8)
            sequences: list[list[Image.Image]] = []
            glow_sequences: list[list[Image.Image] | None] = []
            duration_sequences: list[list[int]] = []
            prepared_by_path: dict[
                tuple[Path, str | None],
                tuple[list[Image.Image], list[int], list[Image.Image] | None],
            ] = {}
            for animation, die_glow_color in zip(animations, glow_colors):
                prepared_key = (animation.path, die_glow_color)
                prepared = prepared_by_path.get(prepared_key)
                if prepared is None:
                    frames, durations = self._load_animation(animation.path)
                    if not frames:
                        raise ValueError(
                            f"Dice animation has no frames: {animation.path}"
                        )
                    prepared_frames = [
                        frame.resize(
                            (inner_size, inner_size),
                            Image.Resampling.LANCZOS,
                        )
                        for frame in frames
                    ]
                    prepared = (
                        prepared_frames,
                        durations,
                        (
                            [
                                self._glow_image(
                                    frame,
                                    die_glow_color,
                                    max(3, tile_size // 32),
                                )
                                for frame in prepared_frames
                            ]
                            if die_glow_color is not None
                            else None
                        ),
                    )
                    prepared_by_path[prepared_key] = prepared
                prepared_frames, durations, prepared_glows = prepared
                sequences.append(prepared_frames)
                duration_sequences.append(durations)
                glow_sequences.append(prepared_glows)

            timeline_index = max(
                range(len(sequences)), key=lambda index: len(sequences[index])
            )
            frame_count = len(sequences[timeline_index])
            durations = duration_sequences[timeline_index]
            composed_frames: list[Image.Image] = []
            for frame_index in range(frame_count):
                canvas = Image.new(
                    "RGBA", (tile_size * len(animations), tile_size)
                )
                for die_index, source_frames in enumerate(sequences):
                    source_index = (
                        0
                        if frame_count == 1
                        else round(
                            frame_index
                            * (len(source_frames) - 1)
                            / (frame_count - 1)
                        )
                    )
                    if glow_sequences[die_index] is not None:
                        canvas.alpha_composite(
                            glow_sequences[die_index][source_index],
                            (die_index * tile_size + 4, 4),
                        )
                    canvas.alpha_composite(
                        source_frames[source_index],
                        (die_index * tile_size + 4, 4),
                    )
                composed_frames.append(canvas)

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            composed_frames[0].save(
                temporary_path,
                format="GIF",
                save_all=True,
                append_images=composed_frames[1:],
                duration=durations,
                disposal=2,
                optimize=False,
            )
            self._save_group_result_image(
                [animation.result_image_path for animation in animations],
                temporary_result_path,
                glow_colors,
            )
            temporary_path.replace(cache_path)
            temporary_result_path.replace(result_image_path)
            return RenderedDiceAnimation(
                cache_path, sum(durations) / 1000, result_image_path
            )
        except (OSError, ValueError):
            LOGGER.warning("Could not compose dice animations", exc_info=True)
            temporary_path.unlink(missing_ok=True)
            temporary_result_path.unlink(missing_ok=True)
            return None

    @staticmethod
    def _load_animation(path: Path) -> tuple[list[Image.Image], list[int]]:
        frames: list[Image.Image] = []
        durations: list[int] = []
        with Image.open(path) as source:
            default_duration = int(source.info.get("duration", 100) or 100)
            for frame in ImageSequence.Iterator(source):
                frames.append(frame.convert("RGBA"))
                durations.append(
                    int(frame.info.get("duration", default_duration) or 100)
                )
        return frames, durations

    @staticmethod
    def _save_group_result_image(
        paths: list[Path],
        output_path: Path,
        glow_colors: tuple[str | None, ...] | None = None,
    ) -> None:
        images: list[Image.Image] = []
        for path in paths:
            with Image.open(path) as source:
                images.append(source.convert("RGBA"))

        canvas = Image.new(
            "RGBA",
            (GROUP_RESULT_TILE_SIZE * len(images), RESULT_IMAGE_SIZE),
        )
        placements: list[tuple[Image.Image, tuple[int, int]]] = []
        for index, image in enumerate(images):
            die = D20AnimationRenderer._fit_visible_die(image, 126)
            placements.append(
                (
                    die,
                    (
                        index * GROUP_RESULT_TILE_SIZE
                        + (GROUP_RESULT_TILE_SIZE - die.width) // 2,
                        (RESULT_IMAGE_SIZE - die.height) // 2,
                    ),
                )
            )
        if glow_colors is None:
            glow_colors = tuple(None for _ in placements)
        for (die, position), die_glow_color in zip(placements, glow_colors):
            if die_glow_color is not None:
                placed_alpha = Image.new("L", canvas.size)
                placed_alpha.paste(die.getchannel("A"), position)
                canvas.alpha_composite(
                    D20AnimationRenderer._glow_from_alpha(
                        placed_alpha,
                        die_glow_color,
                        radius=5,
                    )
                )
        for die, position in placements:
            canvas.alpha_composite(die, position)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="PNG", optimize=True)

    @staticmethod
    def _hex_rgb(color: str) -> tuple[int, int, int]:
        return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))

    @staticmethod
    def _glow_image(image: Image.Image, color: str, radius: int) -> Image.Image:
        glow = D20AnimationRenderer._glow_from_alpha(
            image.getchannel("A"), color, radius
        )
        glow.putalpha(
            glow.getchannel("A").point(
                lambda value: min(255, round(value * 2.15))
            )
        )
        return D20AnimationRenderer._flatten_glow_for_gif(glow)

    @staticmethod
    def _flatten_glow_for_gif(glow: Image.Image) -> Image.Image:
        """Bake soft alpha against Discord's dark canvas for smooth GIF glow.

        GIF only supports fully transparent or fully opaque palette entries.
        Dithering translucent pixels creates a visibly noisy halo in motion, so
        retain the smooth RGB gradient and use transparency only at its edge.
        """
        alpha = glow.getchannel("A")
        flattened = Image.new(
            "RGBA", glow.size, (*DISCORD_DARK_MATTE, 255)
        )
        flattened.alpha_composite(glow)
        flattened.putalpha(alpha.point(lambda value: 255 if value >= 3 else 0))
        return flattened

    @staticmethod
    def _glow_from_alpha(
        alpha: Image.Image, color: str, radius: int
    ) -> Image.Image:
        rgb = D20AnimationRenderer._hex_rgb(color)
        bright_rgb = tuple(round(channel + (255 - channel) * 0.35) for channel in rgb)
        soft = Image.new("RGBA", alpha.size, (*rgb, 0))
        soft.putalpha(
            alpha.filter(ImageFilter.GaussianBlur(radius=radius * 2)).point(
                lambda value: round(value * 0.18)
            )
        )
        core = Image.new("RGBA", alpha.size, (*bright_rgb, 0))
        core.putalpha(
            alpha.filter(ImageFilter.GaussianBlur(radius=radius)).point(
                lambda value: round(value * 0.48)
            )
        )
        soft.alpha_composite(core)
        return soft

    @staticmethod
    def _fit_visible_die(image: Image.Image, size: int) -> Image.Image:
        box = image.getchannel("A").getbbox()
        if box is None:
            raise ValueError("A dice result image is fully transparent.")
        fitted = image.crop(box)
        fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
        return fitted

    def _generate(
        self,
        master_path: Path,
        cache_path: Path,
        color: str,
        edge_color: str,
        edge_mask_path: Path | None,
        number_color: str,
        number_mask_path: Path | None,
        result_image_path: Path,
        glow_color: str | None,
    ) -> RenderedDiceAnimation | None:
        temporary_path = cache_path.with_suffix(".tmp.gif")
        temporary_result_path = result_image_path.with_name(
            f"{result_image_path.stem}.tmp.png"
        )
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            edge_masks = self._load_masks(edge_mask_path)
            number_masks = self._load_masks(number_mask_path)
            with Image.open(master_path) as source:
                frames: list[Image.Image] = []
                durations: list[int] = []
                settled_frame: Image.Image | None = None
                default_duration = int(source.info.get("duration", 100) or 100)

                for index, frame in enumerate(ImageSequence.Iterator(source)):
                    edge_mask = (
                        edge_masks[min(index, len(edge_masks) - 1)]
                        if edge_masks
                        else None
                    )
                    number_mask = (
                        number_masks[min(index, len(number_masks) - 1)]
                        if number_masks
                        else None
                    )
                    tinted_frame = self._tint_frame(
                        frame.convert("RGBA"),
                        color,
                        edge_color,
                        edge_mask,
                        number_color,
                        number_mask,
                    )
                    settled_frame = tinted_frame
                    frames.append(
                        self._add_glow(tinted_frame, glow_color)
                        if glow_color is not None
                        else tinted_frame
                    )
                    durations.append(int(frame.info.get("duration", default_duration) or 100))

            if not frames or settled_frame is None:
                return None

            frames[0].save(
                temporary_path,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                disposal=2,
                optimize=False,
            )
            self._save_result_image(
                settled_frame, temporary_result_path, glow_color
            )
            temporary_path.replace(cache_path)
            temporary_result_path.replace(result_image_path)
            return RenderedDiceAnimation(
                cache_path, sum(durations) / 1000, result_image_path
            )
        except (OSError, ValueError):
            LOGGER.warning("Could not generate dice animation from %s", master_path, exc_info=True)
            temporary_path.unlink(missing_ok=True)
            temporary_result_path.unlink(missing_ok=True)
            return None

    @staticmethod
    def _save_result_image(
        frame: Image.Image, path: Path, glow_color: str | None = None
    ) -> None:
        """Save a compact transparent crop of the animation's settled frame."""
        box = frame.getchannel("A").getbbox()
        if box is None:
            raise ValueError("The settled dice frame is fully transparent.")

        die = frame.crop(box)
        inner_size = RESULT_IMAGE_SIZE - (34 if glow_color is not None else 16)
        die.thumbnail((inner_size, inner_size), Image.Resampling.LANCZOS)
        thumbnail = Image.new("RGBA", (RESULT_IMAGE_SIZE, RESULT_IMAGE_SIZE))
        position = (
            (RESULT_IMAGE_SIZE - die.width) // 2,
            (RESULT_IMAGE_SIZE - die.height) // 2,
        )
        if glow_color is not None:
            placed_alpha = Image.new("L", thumbnail.size)
            placed_alpha.paste(die.getchannel("A"), position)
            thumbnail.alpha_composite(
                D20AnimationRenderer._glow_from_alpha(
                    placed_alpha, glow_color, radius=5
                )
            )
        thumbnail.alpha_composite(die, position)
        path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail.save(path, format="PNG", optimize=True)

    @staticmethod
    def _add_glow(frame: Image.Image, color: str) -> Image.Image:
        glowing = Image.new("RGBA", frame.size)
        glowing.alpha_composite(
            D20AnimationRenderer._glow_image(
                frame, color, radius=max(3, min(frame.size) // 32)
            )
        )
        glowing.alpha_composite(frame)
        return glowing

    @staticmethod
    def _tint_frame(
        frame: Image.Image,
        color: str,
        edge_color: str | None = None,
        edge_mask: Image.Image | None = None,
        number_color: str | None = None,
        number_mask: Image.Image | None = None,
    ) -> Image.Image:
        """Map neutral luminance through black -> chosen color -> white.

        Transparency is retained, and chromatic pixels are left alone so a colored
        background or decoration in a master asset is not accidentally recolored.
        Neutral master assets should use a transparent background.
        """
        face_tinted = D20AnimationRenderer._tint_neutral(
            frame, color, preserve_body_color=True
        )
        tinted = face_tinted
        if edge_color is not None and edge_mask is not None:
            edge_tinted = D20AnimationRenderer._tint_neutral(frame, edge_color)
            if edge_mask.size != frame.size:
                edge_mask = edge_mask.resize(frame.size, Image.Resampling.BILINEAR)
            tinted = Image.composite(edge_tinted, tinted, edge_mask.convert("L"))

        if number_color is not None and number_mask is not None:
            number_tinted = D20AnimationRenderer._tint_neutral(frame, number_color)
            if number_mask.size != frame.size:
                number_mask = number_mask.resize(frame.size, Image.Resampling.BILINEAR)
            tinted = Image.composite(
                number_tinted, tinted, number_mask.convert("L")
            )
        return tinted

    @staticmethod
    def _tint_neutral(
        frame: Image.Image,
        color: str,
        preserve_body_color: bool = False,
    ) -> Image.Image:
        target = tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))
        tinted_pixels: list[tuple[int, int, int, int]] = []

        for red, green, blue, alpha in frame.getdata():
            if alpha == 0 or max(red, green, blue) - min(red, green, blue) > 18:
                tinted_pixels.append((red, green, blue, alpha))
                continue

            luminance = round(0.2126 * red + 0.7152 * green + 0.0722 * blue)
            if preserve_body_color:
                # Treat the brightest neutral surface as the chosen body color,
                # with only a restrained neutral highlight. Mapping it to pure
                # white makes well-lit masters appear white instead of colored.
                shade = 0.25 + 0.75 * luminance / 255
                highlight = round(luminance * 0.08)
                channels = tuple(
                    min(255, round(channel * shade + highlight))
                    for channel in target
                )
            elif luminance <= 128:
                channels = tuple(round(channel * luminance / 128) for channel in target)
            else:
                amount = (luminance - 128) / 127
                channels = tuple(
                    round(channel + (255 - channel) * amount) for channel in target
                )
            tinted_pixels.append((*channels, alpha))

        tinted = Image.new("RGBA", frame.size)
        tinted.putdata(tinted_pixels)
        return tinted

    @staticmethod
    def _load_masks(path: Path | None) -> list[Image.Image]:
        if path is None:
            return []
        masks: list[Image.Image] = []
        try:
            with Image.open(path) as source:
                for frame in ImageSequence.Iterator(source):
                    rgba = frame.convert("RGBA")
                    luminance = ImageOps.grayscale(rgba)
                    masks.append(ImageChops.multiply(luminance, rgba.getchannel("A")))
        except (OSError, ValueError):
            LOGGER.warning("Could not read dice mask %s", path, exc_info=True)
            return []
        return masks

    @staticmethod
    def _animation_duration(path: Path) -> float | None:
        try:
            with Image.open(path) as image:
                default_duration = int(image.info.get("duration", 100) or 100)
                duration_ms = sum(
                    int(frame.info.get("duration", default_duration) or 100)
                    for frame in ImageSequence.Iterator(image)
                )
            return duration_ms / 1000
        except (OSError, ValueError):
            return None
