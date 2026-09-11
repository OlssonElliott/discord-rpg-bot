import os
import unittest
from unittest.mock import patch

from rpg_bot.config import Config
from rpg_bot.dice_assets import InvalidDiceThemeError
from rpg_bot.__main__ import REQUIRED_BOT_PERMISSIONS


class ConfigTests(unittest.TestCase):
    def test_required_bot_permissions_cover_private_map_and_dice_audio(self) -> None:
        for permission in (
            "manage_channels",
            "view_channel",
            "send_messages",
            "embed_links",
            "attach_files",
            "read_message_history",
            "connect",
            "speak",
        ):
            with self.subTest(permission=permission):
                self.assertTrue(getattr(REQUIRED_BOT_PERMISSIONS, permission))

    def test_dice_theme_defaults_to_classic_and_normalizes(self) -> None:
        with patch("rpg_bot.config.load_dotenv"), patch.dict(
            os.environ, {"DISCORD_TOKEN": "token"}, clear=True
        ):
            self.assertEqual(Config.from_env().dice_theme, "classic")
            self.assertEqual(
                Config.from_env().character_media_path, "data/characters"
            )

        with patch("rpg_bot.config.load_dotenv"), patch.dict(
            os.environ,
            {"DISCORD_TOKEN": "token", "DICE_THEME": " Cartoon "},
            clear=True,
        ):
            self.assertEqual(Config.from_env().dice_theme, "cartoon")

    def test_invalid_dice_theme_is_rejected(self) -> None:
        with patch("rpg_bot.config.load_dotenv"), patch.dict(
            os.environ,
            {"DISCORD_TOKEN": "token", "DICE_THEME": "../cartoon"},
            clear=True,
        ):
            with self.assertRaises(InvalidDiceThemeError):
                Config.from_env()

    def test_character_media_path_can_be_configured(self) -> None:
        with patch("rpg_bot.config.load_dotenv"), patch.dict(
            os.environ,
            {"DISCORD_TOKEN": "token", "CHARACTER_MEDIA_PATH": "var/portraits"},
            clear=True,
        ):
            self.assertEqual(
                Config.from_env().character_media_path, "var/portraits"
            )


if __name__ == "__main__":
    unittest.main()
