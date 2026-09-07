import tempfile
import unittest
from pathlib import Path

from rpg_bot.dice_assets import (
    DiceAsset,
    DiceAssetLayout,
    InvalidDiceThemeError,
    normalize_dice_theme,
)


class DiceAssetTests(unittest.TestCase):
    def test_theme_names_are_normalized_and_validated(self) -> None:
        self.assertEqual(normalize_dice_theme(" Cartoon "), "cartoon")
        self.assertEqual(normalize_dice_theme("dark-fantasy"), "dark-fantasy")
        for theme in (
            "../cartoon",
            "dark_fantasy",
            "a/b",
            "-classic",
            "two--hyphens",
            "a" * 65,
        ):
            with self.subTest(theme=theme):
                with self.assertRaises(InvalidDiceThemeError):
                    normalize_dice_theme(theme)

    def test_themed_master_and_cache_paths_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            layout = DiceAssetLayout(directory)
            classic = layout.master_path(20, "classic", 17)
            cartoon = layout.master_path(20, "cartoon", 17)
            classic_cache = layout.cache_path(
                20, "classic", "#7A2EFF", 17, "#303030", "#101010"
            )
            cartoon_cache = layout.cache_path(
                20, "cartoon", "#7A2EFF", 17, "#FFD700", "#F5F5F5"
            )

            self.assertEqual(
                cartoon,
                Path(directory) / "d20" / "themes" / "cartoon" / "d20_17.gif",
            )
            self.assertNotEqual(classic, cartoon)
            self.assertNotEqual(classic_cache, cartoon_cache)
            self.assertEqual(
                cartoon_cache,
                Path(directory)
                / "d20"
                / "cache"
                / "v2"
                / "cartoon"
                / "7A2EFF"
                / "FFD700"
                / "F5F5F5"
                / "d20_17.gif",
            )
            self.assertEqual(
                layout.edge_mask_path(DiceAsset(cartoon, "cartoon")),
                cartoon.with_name("d20_17_edges.gif"),
            )
            self.assertEqual(
                layout.number_mask_path(DiceAsset(cartoon, "cartoon")),
                cartoon.with_name("d20_17_numbers.gif"),
            )


if __name__ == "__main__":
    unittest.main()
