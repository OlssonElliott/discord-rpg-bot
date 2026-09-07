from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from rpg_bot.portraits import (
    CharacterPortraitStore,
    InvalidPortraitError,
    default_portrait_key,
)


def image_bytes(size: tuple[int, int] = (400, 200), image_format: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "purple").save(output, format=image_format)
    return output.getvalue()


class CharacterPortraitStoreTests(unittest.TestCase):
    def test_every_character_race_resolves_to_a_default_portrait(self) -> None:
        store = CharacterPortraitStore()
        gendered = ("Human", "Dwarf", "Halfling", "Elf")
        shared = (
            "Dryad",
            "Faun",
            "Gnoll",
            "Lizardman",
            "Minotaur",
            "Orc",
            "Troll",
            "Goblin",
            "Revenant",
            "Hagspawn",
            "Swarmling",
        )
        for race in gendered:
            for gender in ("Male", "Female"):
                with self.subTest(race=race, gender=gender):
                    key = default_portrait_key(race, gender)
                    path = store.path_for(key)
                    self.assertIsNotNone(path)
                    assert path is not None
                    with Image.open(path) as portrait:
                        portrait.verify()
        for race in shared:
            with self.subTest(race=race):
                male_key = default_portrait_key(race, "Male")
                female_key = default_portrait_key(race, "Female")
                self.assertEqual(male_key, female_key)
                path = store.path_for(male_key)
                self.assertIsNotNone(path)
                assert path is not None
                with Image.open(path) as portrait:
                    portrait.verify()

    def test_portrait_is_cropped_and_standardized_as_webp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CharacterPortraitStore(directory)
            key = store.save(42, image_bytes())
            path = store.path_for(key)

            self.assertRegex(key, r"^42/portrait-[0-9a-f]{32}\.webp$")
            self.assertEqual(path, Path(directory) / key)
            assert path is not None
            with Image.open(path) as portrait:
                self.assertEqual(portrait.format, "WEBP")
                self.assertEqual(portrait.size, (256, 256))

    def test_invalid_or_oversized_upload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CharacterPortraitStore(directory)
            with self.assertRaises(InvalidPortraitError):
                store.save(1, b"not an image")
            with self.assertRaises(InvalidPortraitError):
                store.save(1, b"x" * (5 * 1024 * 1024 + 1))

    def test_untrusted_storage_keys_cannot_escape_media_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CharacterPortraitStore(directory)
            self.assertIsNone(store.path_for("../portrait.webp"))
            self.assertIsNone(store.path_for("1/../../portrait.webp"))

    def test_remove_deletes_the_saved_portrait(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CharacterPortraitStore(directory)
            key = store.save(7, image_bytes())
            store.remove(key)
            self.assertIsNone(store.path_for(key))

    def test_remove_never_deletes_a_shared_default_portrait(self) -> None:
        store = CharacterPortraitStore()
        key = default_portrait_key("Human", "Male")
        path = store.path_for(key)
        self.assertIsNotNone(path)

        store.remove(key)

        self.assertEqual(store.path_for(key), path)


if __name__ == "__main__":
    unittest.main()
