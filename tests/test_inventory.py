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

    def test_nested_container_weight_rolls_up_to_equipped_container(self) -> None:
        backpack_id = self.service.grant(self.character, "traveler_backpack")
        satchel_id = self.service.grant(self.character, "small_satchel")
        dagger_id = self.service.grant(self.character, "iron_dagger")

        self.service.move_to_container(self.character, satchel_id, backpack_id)
        self.service.move_to_container(self.character, dagger_id, satchel_id)
        self.service.equip(self.character, backpack_id)
        inventory = self.database.get_character_inventory(self.character.character_id)

        self.assertEqual(inventory.container_storage(satchel_id, self.catalog), 1)
        self.assertEqual(inventory.container_storage(backpack_id, self.catalog), 2)
        self.assertEqual(inventory.current_storage(self.catalog), 0)
        self.assertEqual(inventory.current_weight(self.catalog), 4)

    def test_containers_cannot_create_cycles_or_exceed_capacity(self) -> None:
        backpack_id = self.service.grant(self.character, "traveler_backpack")
        satchel_id = self.service.grant(self.character, "small_satchel")
        axe_id = self.service.grant(self.character, "great_axe")
        self.service.move_to_container(self.character, satchel_id, backpack_id)

        with self.assertRaisesRegex(InventoryError, "inside itself"):
            self.service.move_to_container(self.character, backpack_id, satchel_id)
        with self.assertRaisesRegex(InventoryError, "enough capacity"):
            self.service.move_to_container(self.character, axe_id, satchel_id)

    def test_using_one_consumable_decrements_its_stack(self) -> None:
        potion_id = self.service.grant(self.character, "stale_bread", 2)
        self.database.damage(7, 10)

        updated = self.service.use(self.database.get_character(7), potion_id)
        inventory = self.database.get_character_inventory(self.character.character_id)

        self.assertEqual(updated.hp, 10)
        self.assertEqual(inventory.item(potion_id).quantity, 1)


if __name__ == "__main__":
    unittest.main()
