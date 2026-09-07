import tempfile
import unittest
from pathlib import Path
import sqlite3

from rpg_bot.database import (
    CharacterAlreadyExistsError,
    CharacterNotFoundError,
    Database,
    InvalidHitPointsError,
)
from rpg_bot.dice_visuals import (
    DEFAULT_DICE_COLOR,
    DEFAULT_DICE_EDGE_COLOR,
    DEFAULT_DICE_NUMBER_COLOR,
    InvalidDiceColorError,
)
from rpg_bot.models import Stance


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
            self.database.create_character(123, "olof", 10)
        with self.assertRaises(ValueError):
            self.database.create_character(456, "x" * 101, 10)
        with self.assertRaises(InvalidHitPointsError):
            self.database.set_hp(123, 23)
        with self.assertRaises(CharacterNotFoundError):
            self.database.damage(999, 1)

    def test_user_can_select_between_multiple_characters(self) -> None:
        first = self.database.create_character(123, "Olof", 22)
        second = self.database.create_character(123, "Aria", 12)

        self.assertFalse(self.database.get_character_by_id(123, first.character_id).is_active)
        self.assertTrue(second.is_active)
        self.assertEqual(
            [character.name for character in self.database.list_characters(123)],
            ["Aria", "Olof"],
        )

        selected = self.database.select_character(123, first.character_id)

        self.assertEqual(selected.name, "Olof")
        self.assertEqual(self.database.get_character(123).character_id, first.character_id)

        self.database.deactivate_character(123)

        self.assertIsNone(self.database.get_character(123))
        self.assertEqual(len(self.database.list_characters(123)), 2)

    def test_archiving_keeps_data_but_removes_character_from_selection(self) -> None:
        first = self.database.create_character(123, "Olof", 22)
        second = self.database.create_character(123, "Aria", 12)

        archived = self.database.archive_character(123, second.character_id)

        self.assertTrue(archived.is_archived)
        self.assertFalse(archived.is_active)
        self.assertEqual(
            [character.name for character in self.database.list_characters(123)],
            ["Olof"],
        )
        self.assertEqual(self.database.get_character(123).character_id, first.character_id)
        self.assertIsNone(self.database.get_character_by_id(123, second.character_id))
        self.assertIsNotNone(
            self.database.get_character_by_id(
                123, second.character_id, include_archived=True
            )
        )
        with self.assertRaises(CharacterNotFoundError):
            self.database.select_character(123, second.character_id)

    def test_character_portrait_can_be_set_replaced_and_removed(self) -> None:
        created = self.database.create_character(123, "Olof", 22)

        updated = self.database.set_character_portrait(
            123, created.character_id, f"{created.character_id}/portrait.webp"
        )
        self.assertEqual(
            updated.portrait_key, f"{created.character_id}/portrait.webp"
        )
        self.assertEqual(
            self.database.get_character(123).portrait_key,
            f"{created.character_id}/portrait.webp",
        )

        removed = self.database.set_character_portrait(123, created.character_id, None)
        self.assertIsNone(removed.portrait_key)

        with self.assertRaises(CharacterNotFoundError):
            self.database.set_character_portrait(999, created.character_id, "bad")

    def test_new_character_gets_default_portrait_from_race_and_gender(self) -> None:
        gendered = self.database.create_character(
            123, "Aria", 11, race="Elf", gender="Female"
        )
        shared = self.database.create_character(
            456, "Grak", 14, race="Orc", gender="Male"
        )

        self.assertEqual(gendered.portrait_key, "default/elf_female.png")
        self.assertEqual(shared.portrait_key, "default/orc.png")

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

    def test_existing_character_table_gains_creation_columns(self) -> None:
        old_path = Path(self.temp_directory.name) / "old-characters.db"
        connection = sqlite3.connect(old_path)
        try:
            connection.execute(
                """
                CREATE TABLE characters (
                    discord_user_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    hp INTEGER NOT NULL,
                    max_hp INTEGER NOT NULL,
                    stance TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO characters VALUES (?, ?, ?, ?, ?)",
                (42, "Legacy", 8, 10, "steady"),
            )
            connection.execute(
                """
                CREATE TABLE character_skills (
                    discord_user_id INTEGER NOT NULL,
                    skill TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    PRIMARY KEY (discord_user_id, skill)
                )
                """
            )
            connection.execute(
                "INSERT INTO character_skills VALUES (?, ?, ?)",
                (42, "Survival", 1),
            )
            connection.commit()
        finally:
            connection.close()

        migrated = Database(old_path)
        migrated.initialize()
        character = migrated.get_character(42)

        self.assertIsNotNone(character)
        assert character is not None
        self.assertEqual(character.name, "Legacy")
        self.assertIsNone(character.lineage)
        self.assertEqual(character.attributes, {})
        self.assertEqual(character.skills, {"Survival": 1})
        self.assertIsNotNone(character.character_id)
        self.assertTrue(character.is_active)
        self.assertIsNone(character.portrait_key)


if __name__ == "__main__":
    unittest.main()
