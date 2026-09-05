import tempfile
import unittest
from pathlib import Path

from database import (
    CharacterAlreadyExistsError,
    CharacterNotFoundError,
    Database,
    InvalidHitPointsError,
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


if __name__ == "__main__":
    unittest.main()
