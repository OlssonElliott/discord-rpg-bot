import tempfile
import unittest
from pathlib import Path
import sqlite3

from rpg_bot.database import Database
from rpg_bot.inventory import (
    DEFAULT_ITEM_CATALOG_PATH,
    EquipmentSlot,
    ItemCatalog,
    ItemTemplate,
    ItemType,
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
        potion = inventory.item(first_id)
        self.assertEqual(potion.quantity, 5)

    def test_character_starts_in_weightless_common_clothing(self) -> None:
        inventory = self.database.get_character_inventory(self.character.character_id)
        clothing_id = inventory.equipment[EquipmentSlot.CLOTHING]

        self.assertEqual(inventory.item(clothing_id).template_id, "common_clothing")
        self.assertEqual(inventory.current_storage(self.catalog), 0)
        self.assertEqual(inventory.current_weight(self.catalog), 0)

    def test_armor_is_worn_over_clothing_and_does_not_replace_it(self) -> None:
        inventory = self.database.get_character_inventory(self.character.character_id)
        clothing_id = inventory.equipment[EquipmentSlot.CLOTHING]
        armor_id = self.service.grant(self.character, "leather_armor")

        self.service.equip(self.character, armor_id)
        equipped = self.database.get_character_inventory(self.character.character_id)
        self.assertEqual(equipped.equipment[EquipmentSlot.CLOTHING], clothing_id)
        self.assertEqual(equipped.equipment[EquipmentSlot.ARMOR], armor_id)

        self.service.unequip(self.character, armor_id)
        unarmored = self.database.get_character_inventory(self.character.character_id)
        self.assertEqual(unarmored.equipment[EquipmentSlot.CLOTHING], clothing_id)
        self.assertNotIn(EquipmentSlot.ARMOR, unarmored.equipment)

    def test_equipping_other_clothes_replaces_common_clothing(self) -> None:
        fine_clothes = ItemTemplate(
            template_id="fine_clothing",
            item_type=ItemType.CLOTHING,
            name="Fine Clothing",
            rarity="Uncommon",
            value=20,
            description="Tailored clothes.",
            weight=0,
        )
        service = InventoryService(
            self.database, ItemCatalog((*self.catalog.all(), fine_clothes))
        )
        fine_id = self.database.add_inventory_item(
            self.character.character_id, fine_clothes.template_id
        )

        slot = service.equip(self.character, fine_id)
        inventory = self.database.get_character_inventory(self.character.character_id)

        self.assertEqual(slot, EquipmentSlot.CLOTHING)
        self.assertEqual(inventory.equipment[EquipmentSlot.CLOTHING], fine_id)
        common = next(
            item for item in inventory.items if item.template_id == "common_clothing"
        )
        self.assertNotIn(common.instance_id, inventory.equipment.values())

    def test_existing_equipment_table_is_migrated_and_gets_default_clothing(self) -> None:
        inventory = self.database.get_character_inventory(self.character.character_id)
        clothing_id = inventory.equipment[EquipmentSlot.CLOTHING]
        self.service.unequip(self.character, clothing_id)
        self.database.set_inventory_item_quantity(
            self.character.character_id, clothing_id, 0
        )
        connection = sqlite3.connect(self.database.path)
        try:
            connection.execute(
                "ALTER TABLE character_equipment RENAME TO character_equipment_new"
            )
            connection.execute(
                """
                CREATE TABLE character_equipment (
                    character_id INTEGER NOT NULL,
                    slot TEXT NOT NULL CHECK (
                        slot IN ('main_hand', 'off_hand', 'armor', 'container')
                    ),
                    item_instance_id TEXT NOT NULL,
                    PRIMARY KEY (character_id, slot),
                    UNIQUE (character_id, item_instance_id)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO character_equipment
                SELECT * FROM character_equipment_new
                """
            )
            connection.execute("DROP TABLE character_equipment_new")
            connection.commit()
        finally:
            connection.close()

        self.database.initialize()
        migrated = self.database.get_character_inventory(self.character.character_id)

        migrated_clothing_id = migrated.equipment[EquipmentSlot.CLOTHING]
        self.assertEqual(
            migrated.item(migrated_clothing_id).template_id, "common_clothing"
        )

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

    def test_read_returns_content_without_consuming_readable(self) -> None:
        note = ItemTemplate(
            template_id="bloodstained_note",
            item_type=ItemType.READABLE,
            name="Bloodstained Note",
            rarity="Common",
            value=0,
            description="A folded note stained with old blood.",
            weight=0,
            content="Do not open the western gate after sunset...",
        )
        catalog = ItemCatalog((*self.catalog.all(), note))
        service = InventoryService(self.database, catalog)
        note_id = service.grant(self.character, note.template_id)
        before = self.database.get_character_inventory(self.character.character_id)

        read_result = service.read(self.character, note_id)
        with self.assertRaisesRegex(InventoryError, "not consumable"):
            service.use(self.character, note_id)
        after = self.database.get_character_inventory(self.character.character_id)

        self.assertEqual(read_result.content, note.content)
        self.assertEqual(after.items, before.items)


class ItemCatalogTests(unittest.TestCase):
    def test_readable_content_persists_and_can_be_edited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.json"
            path.write_text("[]\n", encoding="utf-8")
            catalog = ItemCatalog.load(path)
            record = {
                "item_type": "readable",
                "id": "old_journal",
                "name": "Old Journal",
                "rarity": "Common",
                "value": 4,
                "description": "A weathered leather journal.",
                "weight": 1,
                "content": "First entry.\nSecond entry.",
            }

            catalog.create(record)
            catalog.update(
                "old_journal", {**record, "content": "A corrected final entry."}
            )
            reloaded = ItemCatalog.load(path)

            readable = reloaded.get("old_journal")
            self.assertEqual(readable.item_type, ItemType.READABLE)
            self.assertEqual(readable.description, record["description"])
            self.assertEqual(readable.content, "A corrected final entry.")

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
