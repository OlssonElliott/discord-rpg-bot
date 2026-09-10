import tempfile
import unittest
from pathlib import Path

from rpg_bot.database import Database
from rpg_bot.inventory import (
    DEFAULT_ITEM_CATALOG_PATH,
    EquipmentSlot,
    ItemCatalog,
)
from rpg_bot.inventory_service import InventoryError, InventoryService


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_directory.name) / "inventory.db")
        self.database.initialize()
        self.catalog = ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)
        self.service = InventoryService(self.database, self.catalog)
        self.character = self.database.create_character(
            7,
            "Olof",
            15,
            attributes={"Strength": 14, "Vitality": 15},
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_consumables_stack_by_template_and_quantity(self) -> None:
        first_id = self.service.grant(self.character, "health_potion", 2)
        second_id = self.service.grant(self.character, "health_potion", 3)

        inventory = self.database.get_character_inventory(self.character.character_id)

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(inventory.items), 1)
        self.assertEqual(inventory.items[0].quantity, 5)

    def test_equipment_counts_as_weight_but_not_regular_storage(self) -> None:
        axe_id = self.service.grant(self.character, "great_axe")
        before = self.database.get_character_inventory(self.character.character_id)
        self.assertEqual(before.current_storage(self.catalog), 4)

        slot = self.service.equip(self.character, axe_id)
        equipped = self.database.get_character_inventory(self.character.character_id)

        self.assertEqual(slot, EquipmentSlot.MAIN_HAND)
        self.assertEqual(equipped.current_storage(self.catalog), 0)
        self.assertEqual(equipped.current_weight(self.catalog), 4)

    def test_equipped_backpack_adds_capacity_without_hiding_items(self) -> None:
        backpack_id = self.service.grant(self.character, "traveler_backpack")
        dagger_id = self.service.grant(self.character, "iron_dagger")

        loose = self.database.get_character_inventory(self.character.character_id)
        self.assertEqual(loose.storage_capacity(self.catalog), 20)
        self.assertEqual(loose.current_storage(self.catalog), 3)

        self.service.equip(self.character, backpack_id)
        inventory = self.database.get_character_inventory(self.character.character_id)

        self.assertEqual(inventory.storage_capacity(self.catalog), 26)
        self.assertEqual(inventory.current_storage(self.catalog), 1)
        self.assertEqual(inventory.current_weight(self.catalog), 3)
        self.assertIsNone(inventory.item(dagger_id).parent_container_id)

    def test_backpack_cannot_be_unequipped_when_inventory_would_overflow(self) -> None:
        backpack_id = self.service.grant(self.character, "traveler_backpack")
        self.service.equip(self.character, backpack_id)
        for _ in range(6):
            self.service.grant(self.character, "great_axe")

        with self.assertRaisesRegex(InventoryError, "unequip"):
            self.service.unequip(self.character, backpack_id)

        inventory = self.database.get_character_inventory(self.character.character_id)
        self.assertEqual(inventory.storage_capacity(self.catalog), 26)
        self.assertEqual(inventory.current_storage(self.catalog), 24)

    def test_initialize_flattens_items_from_the_old_container_model(self) -> None:
        backpack_id = self.service.grant(self.character, "traveler_backpack")
        dagger_id = self.service.grant(self.character, "iron_dagger")
        self.database.move_inventory_item(
            self.character.character_id, dagger_id, backpack_id
        )

        self.database.initialize()
        inventory = self.database.get_character_inventory(self.character.character_id)

        self.assertIsNone(inventory.item(dagger_id).parent_container_id)

    def test_using_one_consumable_decrements_its_stack(self) -> None:
        potion_id = self.service.grant(self.character, "stale_bread", 2)
        self.database.damage(7, 10)

        updated = self.service.use(self.database.get_character(7), potion_id)
        inventory = self.database.get_character_inventory(self.character.character_id)

        self.assertEqual(updated.hp, 10)
        self.assertEqual(inventory.item(potion_id).quantity, 1)


class ItemCatalogTests(unittest.TestCase):
    def test_other_process_view_reloads_after_catalog_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.json"
            path.write_text("[]\n", encoding="utf-8")
            writer = ItemCatalog.load(path)
            reader = ItemCatalog.load(path)

            writer.create(
                {
                    "item_type": "misc",
                    "id": "iron_key",
                    "name": "Iron Key",
                    "rarity": "Common",
                    "value": 2,
                    "description": "Opens the crypt.",
                    "weight": 0,
                    "tags": [],
                    "modifiers": [],
                    "requirements": [],
                }
            )

            self.assertEqual(reader.get("iron_key").name, "Iron Key")

    def test_catalog_rejects_duplicate_item_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.json"
            path.write_text("[]\n", encoding="utf-8")
            catalog = ItemCatalog.load(path)
            record = {
                "item_type": "misc",
                "id": "iron_key",
                "name": "Iron Key",
                "rarity": "Common",
                "value": 2,
                "description": "",
                "weight": 0,
                "tags": [],
                "modifiers": [],
                "requirements": [],
            }
            catalog.create(record)

            with self.assertRaisesRegex(ValueError, "already exists"):
                catalog.create({**record, "id": "another_key"})


if __name__ == "__main__":
    unittest.main()
