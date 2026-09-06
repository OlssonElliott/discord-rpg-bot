import os
import unittest
from unittest.mock import patch

from config import Config
from dice_assets import InvalidDiceThemeError


class ConfigTests(unittest.TestCase):
    def test_dice_theme_defaults_to_classic_and_normalizes(self) -> None:
        with patch("config.load_dotenv"), patch.dict(
            os.environ, {"DISCORD_TOKEN": "token"}, clear=True
        ):
            self.assertEqual(Config.from_env().dice_theme, "classic")

        with patch("config.load_dotenv"), patch.dict(
            os.environ,
            {"DISCORD_TOKEN": "token", "DICE_THEME": " Cartoon "},
            clear=True,
        ):
            self.assertEqual(Config.from_env().dice_theme, "cartoon")

    def test_invalid_dice_theme_is_rejected(self) -> None:
        with patch("config.load_dotenv"), patch.dict(
            os.environ,
            {"DISCORD_TOKEN": "token", "DICE_THEME": "../cartoon"},
            clear=True,
        ):
            with self.assertRaises(InvalidDiceThemeError):
                Config.from_env()


if __name__ == "__main__":
    unittest.main()
