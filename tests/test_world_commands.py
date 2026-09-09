import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rpg_bot.commands.world import WorldCommands
from rpg_bot.database import Database
from rpg_bot.world import InventoryHolder


class WorldCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_directory.name) / "world-commands.db")
        self.database.initialize()
        character = self.database.create_character(7, "Olof", 15)
        self.character_id = character.character_id
        self.cog = WorldCommands(self.database)
        area = self.cog.world.create_area("chapel", "Ruined Chapel")
        room = self.cog.world.create_room("entrance", area.id, "Entrance")
        self.cog.world.place_character(self.character_id, room.id)
        self.cog.world.create_item("copper", "Copper Coin")
        self.cog.world.create_item("rusty_key", "Rusty Key", stackable=False)
        self.cog.world.place_item(InventoryHolder.room(room.id), "copper", 3)
        self.cog.world.place_item(InventoryHolder.room(room.id), "rusty_key")
        self.interaction = SimpleNamespace(user=SimpleNamespace(id=7))

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    async def test_take_autocomplete_lists_loose_items_with_quantities(self) -> None:
        choices = await self.cog.loose_item_autocomplete(self.interaction, "")

        self.assertEqual(
            [(choice.name, choice.value) for choice in choices],
            [("Copper Coin (3 here)", "copper"), ("Rusty Key (1 here)", "rusty_key")],
        )

    async def test_take_autocomplete_filters_by_name_or_id(self) -> None:
        by_name = await self.cog.loose_item_autocomplete(self.interaction, "coin")
        by_id = await self.cog.loose_item_autocomplete(self.interaction, "rusty_")

        self.assertEqual([choice.value for choice in by_name], ["copper"])
        self.assertEqual([choice.value for choice in by_id], ["rusty_key"])

    async def test_take_autocomplete_is_empty_without_an_active_room(self) -> None:
        choices = await self.cog.loose_item_autocomplete(
            SimpleNamespace(user=SimpleNamespace(id=999)), ""
        )

        self.assertEqual(choices, [])


if __name__ == "__main__":
    unittest.main()
