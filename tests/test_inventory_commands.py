import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from rpg_bot.commands.dm import DMCommands
from rpg_bot.commands.inventory import InventoryCommands, InventoryView, inventory_embed
from rpg_bot.database import Database
from rpg_bot.inventory import DEFAULT_ITEM_CATALOG_PATH, ItemCatalog
from rpg_bot.inventory_service import InventoryService


def interaction_for(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        client=SimpleNamespace(get_cog=lambda _: None),
        response=SimpleNamespace(
            send_message=AsyncMock(),
            edit_message=AsyncMock(),
        ),
    )


class InventoryCommandTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_inventory_command_opens_a_private_interactive_view(self) -> None:
        self.service.grant(self.character, "iron_dagger")
        cog = InventoryCommands(self.database, self.catalog)
        interaction = interaction_for(7)

        await cog.inventory.callback(cog.inventory.binding, interaction)

        call = interaction.response.send_message.await_args
        self.assertTrue(call.kwargs["ephemeral"])
        self.assertEqual(call.kwargs["embed"].title, "Olof's Inventory")
        self.assertIsInstance(call.kwargs["view"], InventoryView)

    def test_inventory_embed_shows_nested_storage_and_equipment(self) -> None:
        backpack_id = self.service.grant(self.character, "traveler_backpack")
        dagger_id = self.service.grant(self.character, "iron_dagger")
        self.service.move_to_container(self.character, dagger_id, backpack_id)
        self.service.equip(self.character, backpack_id)
        inventory = self.database.get_character_inventory(self.character.character_id)

        embed = inventory_embed(self.character, inventory, self.catalog)

        self.assertIn("Regular storage: **0/20**", embed.description)
        self.assertIn("Carried weight: **3**", embed.description)
        equipment = next(field.value for field in embed.fields if field.name == "Equipment")
        self.assertIn("Traveler Backpack", equipment)

    def test_item_catalog_loads_all_shared_templates(self) -> None:
        self.assertEqual(len(self.catalog.all()), 21)
        self.assertEqual(self.catalog.get("great_axe").weight, 4)
        self.assertEqual(self.catalog.get("health_potion").affected_stat, "hp")

    async def test_dm_can_give_a_stack_of_consumables(self) -> None:
        cog = DMCommands(self.database)
        interaction = interaction_for(99)
        member = SimpleNamespace(id=7)

        await cog.give_item.callback(
            cog.give_item.binding,
            interaction,
            member,
            "health_potion",
            3,
        )

        inventory = self.database.get_character_inventory(self.character.character_id)
        self.assertEqual(inventory.items[0].quantity, 3)
        self.assertIn("Health Potion ×3", interaction.response.send_message.await_args.args[0])
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])


if __name__ == "__main__":
    unittest.main()
