import tempfile
import unittest
from pathlib import Path
import sqlite3

from database import (
    CharacterAlreadyExistsError,
    CharacterNotFoundError,
    Database,
    InvalidHitPointsError,
)
from dice_visuals import (
    DEFAULT_DICE_COLOR,
    DEFAULT_DICE_EDGE_COLOR,
    DEFAULT_DICE_NUMBER_COLOR,
    InvalidDiceColorError,
)
from models import Stance


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "test.db"
        self.database = Database(self.database_path)
        self.database.initialize()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_character_state_persists_between_database_instances(self) -> None:
        created = self.database.create_character(123, "Olof", 22)
        self.assertEqual((created.hp, created.max_hp, created.stance), (22, 22, Stance.STEADY))

        self.database.damage(123, 5)
        reopened = Database(self.database_path)
        character = reopened.get_character(123)

        self.assertIsNotNone(character)
        self.assertEqual(character.hp, 17)

    def test_hp_is_clamped_for_damage_and_healing(self) -> None:
        self.database.create_character(123, "Olof", 22)
        self.assertEqual(self.database.damage(123, 50).hp, 0)
        self.assertEqual(self.database.heal(123, 50).hp, 22)

    def test_stance_and_manual_hp_can_be_updated(self) -> None:
        self.database.create_character(123, "Olof", 22)
        self.assertEqual(self.database.set_hp(123, 7).hp, 7)
        self.assertEqual(self.database.set_stance(123, Stance.PRONE).stance, Stance.PRONE)

    def test_invalid_operations_are_rejected(self) -> None:
        self.database.create_character(123, "Olof", 22)
        with self.assertRaises(CharacterAlreadyExistsError):
            self.database.create_character(123, "Other", 10)
        with self.assertRaises(ValueError):
            self.database.create_character(456, "x" * 101, 10)
        with self.assertRaises(InvalidHitPointsError):
            self.database.set_hp(123, 23)
        with self.assertRaises(CharacterNotFoundError):
            self.database.damage(999, 1)

    def test_dice_color_is_a_user_preference_and_persists(self) -> None:
        self.assertEqual(self.database.get_dice_color(999), DEFAULT_DICE_COLOR)

        self.assertEqual(self.database.set_dice_color(999, "7a2eff"), "#7A2EFF")
        reopened = Database(self.database_path)

        self.assertEqual(reopened.get_dice_color(999), "#7A2EFF")
        self.assertIsNone(reopened.get_character(999))

    def test_invalid_dice_colors_are_rejected_without_changing_preference(self) -> None:
        for color in ("purple", "#12345", "#GG00FF", "#1234567"):
            with self.subTest(color=color):
                with self.assertRaises(InvalidDiceColorError):
                    self.database.set_dice_color(123, color)
        self.assertEqual(self.database.get_dice_color(123), DEFAULT_DICE_COLOR)

    def test_dice_edge_color_is_a_separate_user_preference(self) -> None:
        self.assertEqual(
            self.database.get_dice_edge_color(999), DEFAULT_DICE_EDGE_COLOR
        )

        self.database.set_dice_color(999, "7a2eff")
        self.assertEqual(self.database.set_dice_edge_color(999, "ffd700"), "#FFD700")
        reopened = Database(self.database_path)

        self.assertEqual(reopened.get_dice_color(999), "#7A2EFF")
        self.assertEqual(reopened.get_dice_edge_color(999), "#FFD700")
        self.assertIsNone(reopened.get_character(999))

    def test_dice_number_color_is_a_separate_user_preference(self) -> None:
        self.assertEqual(
            self.database.get_dice_number_color(999), DEFAULT_DICE_NUMBER_COLOR
        )

        self.database.set_dice_color(999, "7a2eff")
        self.assertEqual(
            self.database.set_dice_number_color(999, "f5f5f5"), "#F5F5F5"
        )
        reopened = Database(self.database_path)

        self.assertEqual(reopened.get_dice_color(999), "#7A2EFF")
        self.assertEqual(reopened.get_dice_number_color(999), "#F5F5F5")
        self.assertIsNone(reopened.get_character(999))

    def test_existing_preferences_table_gains_default_edge_color(self) -> None:
        old_path = Path(self.temp_directory.name) / "old.db"
        connection = sqlite3.connect(old_path)
        try:
            connection.execute(
                """
                CREATE TABLE user_preferences (
                    discord_user_id INTEGER PRIMARY KEY,
                    dice_color TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO user_preferences VALUES (?, ?)", (42, "#7A2EFF")
            )
            connection.commit()
        finally:
            connection.close()

        migrated = Database(old_path)
        migrated.initialize()

        self.assertEqual(migrated.get_dice_color(42), "#7A2EFF")
        self.assertEqual(migrated.get_dice_edge_color(42), DEFAULT_DICE_EDGE_COLOR)
        self.assertEqual(
            migrated.get_dice_number_color(42), DEFAULT_DICE_NUMBER_COLOR
        )


if __name__ == "__main__":
    unittest.main()
