"""Shared, filesystem-safe paths for themed dice animation assets."""

from dataclasses import dataclass
from pathlib import Path
import re


DEFAULT_DICE_THEME = "classic"
DICE_CACHE_VERSION = "v2"
_THEME_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class InvalidDiceThemeError(ValueError):
    """Raised when a theme name is unsafe or malformed."""


def normalize_dice_theme(theme: str) -> str:
    normalized = theme.strip().lower()
    if len(normalized) > 64 or _THEME_NAME.fullmatch(normalized) is None:
        raise InvalidDiceThemeError(
            "Dice themes must be 1-64 characters using lowercase letters, numbers, "
            "and single hyphens."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class DiceAsset:
    path: Path
    theme: str
    legacy: bool = False


class DiceAssetLayout:
    """Resolve themed assets for any die size without implementing its renderer."""

    def __init__(self, dice_directory: str | Path | None = None) -> None:
        if dice_directory is None:
            dice_directory = Path(__file__).resolve().parent / "assets" / "dice"
        self.dice_directory = Path(dice_directory)

    def die_directory(self, sides: int) -> Path:
        return self.dice_directory / f"d{sides}"

    def theme_directory(self, sides: int, theme: str) -> Path:
        return self.die_directory(sides) / "themes" / normalize_dice_theme(theme)

    def master_path(self, sides: int, theme: str, result: int) -> Path:
        return self.theme_directory(sides, theme) / f"d{sides}_{result}.gif"

    def legacy_master_path(self, sides: int, result: int) -> Path:
        return self.die_directory(sides) / "master" / f"d{sides}_{result}.gif"

    @staticmethod
    def edge_mask_path(master: DiceAsset) -> Path:
        return master.path.with_name(f"{master.path.stem}_edges.gif")

    @staticmethod
    def number_mask_path(master: DiceAsset) -> Path:
        return master.path.with_name(f"{master.path.stem}_numbers.gif")

    def master_candidates(
        self, sides: int, result: int, selected_theme: str
    ) -> tuple[DiceAsset, ...]:
        selected = normalize_dice_theme(selected_theme)
        candidates = [
            DiceAsset(self.master_path(sides, selected, result), selected)
        ]
        if selected != DEFAULT_DICE_THEME:
            candidates.append(
                DiceAsset(
                    self.master_path(sides, DEFAULT_DICE_THEME, result),
                    DEFAULT_DICE_THEME,
                )
            )
        candidates.append(
            DiceAsset(
                self.legacy_master_path(sides, result),
                DEFAULT_DICE_THEME,
                legacy=True,
            )
        )
        return tuple(candidates)

    def cache_path(
        self,
        sides: int,
        theme: str,
        color: str,
        result: int,
        edge_color: str | None = None,
        number_color: str | None = None,
    ) -> Path:
        normalized_theme = normalize_dice_theme(theme)
        normalized_color = color.removeprefix("#").upper()
        path = (
            self.die_directory(sides)
            / "cache"
            / DICE_CACHE_VERSION
            / normalized_theme
            / normalized_color
        )
        if edge_color is not None:
            path /= edge_color.removeprefix("#").upper()
        if number_color is not None:
            path /= number_color.removeprefix("#").upper()
        return path / f"d{sides}_{result}.gif"
