import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from rpg_bot.commands.dm import DMCommands
from rpg_bot.commands.inventory import (
    InventoryCommands,
    InventoryView,
    forget_open_inventory,
    inventory_embed,
    readable_field_pages,
)
from rpg_bot.database import Database
from rpg_bot.inventory import (
    DEFAULT_ITEM_CATALOG_PATH,
    EquipmentSlot,
    ItemCatalog,
    ItemTemplate,
    ItemType,
)
from rpg_bot.inventory_service import InventoryService


def interaction_for(user_id: int) -> SimpleNamespace:
    message = SimpleNamespace(edit=AsyncMock())
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        client=SimpleNamespace(get_cog=lambda _: None),
        message=message,
        original_response=AsyncMock(return_value=message),
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
        forget_open_inventory(7)
        self.temp_directory.cleanup()

    def readable_service(
        self, content: str = "Do not open the western gate after sunset..."
    ) -> tuple[InventoryService, str, ItemTemplate]:
        template = ItemTemplate(
            template_id="bloodstained_note",
            item_type=ItemType.READABLE,
            name="Bloodstained Note",
            rarity="Common",
            value=0,
            description="A folded note stained with old blood.",
            weight=0,
            content=content,
        )
        service = InventoryService(
            self.database, ItemCatalog((*self.catalog.all(), template))
        )
        return service, service.grant(self.character, template.template_id), template

    async def test_inventory_command_opens_a_private_interactive_view(self) -> None:
        self.service.grant(self.character, "iron_dagger")
        cog = InventoryCommands(self.database, self.catalog)
        interaction = interaction_for(7)

        await cog.inventory.callback(cog.inventory.binding, interaction)

        call = interaction.response.send_message.await_args
        self.assertTrue(call.kwargs["ephemeral"])
        self.assertEqual(call.kwargs["embeds"][0].title, "Olof's Inventory")
        self.assertIsInstance(call.kwargs["view"], InventoryView)

    def test_inventory_embed_shows_flat_storage_and_equipped_capacity(self) -> None:
        backpack_id = self.service.grant(self.character, "traveler_backpack")
        self.service.grant(self.character, "iron_dagger")
        self.service.equip(self.character, backpack_id)
        inventory = self.database.get_character_inventory(self.character.character_id)

        embed = inventory_embed(self.character, inventory, self.catalog)

        self.assertIn("Storage: **1/26**", embed.description)
        self.assertIn("Carried weight: **3**", embed.description)
        equipment = next(field.value for field in embed.fields if field.name == "Equipment")
        self.assertIn("Traveler Backpack", equipment)
        items = next(field.value for field in embed.fields if field.name == "Inventory")
        self.assertIn("Iron Dagger", items)

    def test_inventory_shows_nude_only_after_clothing_is_unequipped(self) -> None:
        inventory = self.database.get_character_inventory(self.character.character_id)
        clothing_id = inventory.equipment[EquipmentSlot.CLOTHING]

        self.service.unequip(self.character, clothing_id)
        inventory = self.database.get_character_inventory(self.character.character_id)
        embed = inventory_embed(self.character, inventory, self.catalog)

        equipment = next(field.value for field in embed.fields if field.name == "Equipment")
        self.assertIn("**Clothing** — Nude", equipment)

    def test_inventory_view_has_no_nested_storage_controls(self) -> None:
        backpack_id = self.service.grant(self.character, "traveler_backpack")
        inventory = self.database.get_character_inventory(self.character.character_id)

        view = InventoryView(
            self.service, 7, self.character.character_id, inventory, backpack_id
        )

        labels = {child.label for child in view.children if hasattr(child, "label")}
        self.assertNotIn("Store…", labels)
        self.assertNotIn("To bag", labels)

    def test_item_actions_are_enabled_only_when_they_apply(self) -> None:
        dagger_id = self.service.grant(self.character, "iron_dagger")
        potion_id = self.service.grant(self.character, "health_potion")
        inventory = self.database.get_character_inventory(self.character.character_id)

        no_selection = InventoryView(
            self.service, 7, self.character.character_id, inventory
        )
        dagger = InventoryView(
            self.service, 7, self.character.character_id, inventory, dagger_id
        )
        potion = InventoryView(
            self.service, 7, self.character.character_id, inventory, potion_id
        )

        self.assertTrue(no_selection.equip_button.disabled)
        self.assertTrue(no_selection.unequip_button.disabled)
        self.assertTrue(no_selection.use_button.disabled)
        self.assertFalse(dagger.equip_button.disabled)
        self.assertTrue(dagger.unequip_button.disabled)
        self.assertTrue(dagger.use_button.disabled)
        self.assertTrue(potion.equip_button.disabled)
        self.assertTrue(potion.unequip_button.disabled)
        self.assertFalse(potion.use_button.disabled)

        self.service.equip(self.character, dagger_id)
        equipped_inventory = self.database.get_character_inventory(
            self.character.character_id
        )
        equipped_dagger = InventoryView(
            self.service,
            7,
            self.character.character_id,
            equipped_inventory,
            dagger_id,
        )
        self.assertTrue(equipped_dagger.equip_button.disabled)
        self.assertFalse(equipped_dagger.unequip_button.disabled)

    async def test_read_opens_separate_panel_without_consuming_item(self) -> None:
        service, note_id, template = self.readable_service()
        inventory = self.database.get_character_inventory(self.character.character_id)

        view = InventoryView(
            service, 7, self.character.character_id, inventory, note_id
        )
        interaction = interaction_for(7)
        await view.read_button.callback(interaction)

        edited = interaction.response.edit_message.await_args.kwargs
        embeds = edited["embeds"]
        self.assertEqual(len(embeds), 2)
        self.assertEqual(embeds[0].title, "Olof's Inventory")
        self.assertEqual(embeds[1].title, template.name)
        self.assertIn(template.description, embeds[1].description)
        self.assertIn(template.content, embeds[1].description)
        self.assertTrue(view.use_button.disabled)
        self.assertEqual(
            self.database.get_character_inventory(
                self.character.character_id
            ).item(note_id).quantity,
            1,
        )

    def test_long_readable_content_is_paginated_without_truncation(self) -> None:
        content = " ".join(f"word-{index}" for index in range(900))
        service, note_id, template = self.readable_service(content)
        pages = readable_field_pages(template)
        inventory = self.database.get_character_inventory(self.character.character_id)
        view = InventoryView(
            service,
            7,
            self.character.character_id,
            inventory,
            note_id,
            reading_id=note_id,
        )

        prefix_end = pages[0].index("──────────\n") + len("──────────\n")
        reconstructed = pages[0][prefix_end:] + "".join(pages[1:])
        self.assertEqual(reconstructed, content)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= 4096 for page in pages))
        labels = {child.label for child in view.children if hasattr(child, "label")}
        self.assertIn(f"Page 1 / {len(pages)}", labels)

    def test_short_readable_has_no_page_controls_and_can_close(self) -> None:
        service, note_id, _ = self.readable_service("Short note.")
        inventory = self.database.get_character_inventory(self.character.character_id)
        view = InventoryView(
            service,
            7,
            self.character.character_id,
            inventory,
            note_id,
            reading_id=note_id,
        )

        labels = [child.label for child in view.children if hasattr(child, "label")]
        self.assertIn("Close reading", labels)
        self.assertNotIn("Page 1 / 1", labels)

    def test_item_catalog_loads_all_shared_templates(self) -> None:
        self.assertGreaterEqual(len(self.catalog.all()), 22)
        self.assertEqual(self.catalog.get("common_clothing").weight, 0)
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
        potion = next(
            item for item in inventory.items if item.template_id == "health_potion"
        )
        self.assertEqual(potion.quantity, 3)
        self.assertIn("Health Potion ×3", interaction.response.send_message.await_args.args[0])
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])


if __name__ == "__main__":
    unittest.main()
