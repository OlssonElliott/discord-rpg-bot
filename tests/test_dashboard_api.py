import tempfile
import unittest
from pathlib import Path

from rpg_bot.dashboard_api import DashboardAPI
from rpg_bot.database import Database
from rpg_bot.inventory import ItemCatalog
from rpg_bot.world import InventoryHolder
from rpg_bot.world_service import WorldService


class DashboardAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_directory.name) / "dashboard.db")
        self.database.initialize()
        self.catalog_path = Path(self.temp_directory.name) / "items.json"
        self.catalog_path.write_text("[]\n", encoding="utf-8")
        self.world = WorldService(self.database, ItemCatalog.load(self.catalog_path))
        self.api = DashboardAPI(self.world)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_graph_can_be_created_and_reconstructed_through_api(self) -> None:
        status, area = self.api.handle(
            "POST", "/api/areas", {"id": "crypt", "name": "Forgotten Crypt"}
        )
        self.assertEqual(status, 201)
        for room_id, name, x in (
            ("entrance", "Entrance", 100),
            ("hall", "Burial Hall", 420),
        ):
            status, _ = self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": name, "description": "", "x": x, "y": 200},
            )
            self.assertEqual(status, 201)
        status, _ = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "destination_room_id": "hall",
                "exit_name": "north",
            },
        )
        self.assertEqual(status, 201)

        status, graph = self.api.handle("GET", "/api/areas/crypt/graph")

        self.assertEqual(status, 200)
        self.assertEqual(graph["area"]["name"], "Forgotten Crypt")
        self.assertEqual(
            [(node["id"], node["position"]["x"]) for node in graph["nodes"]],
            [("entrance", 100.0), ("hall", 420.0)],
        )
        self.assertEqual(len(graph["connections"]), 1)
        self.assertEqual(graph["connections"][0]["exit_name"], "north")
        self.assertEqual(graph["connections"][0]["return_exit_name"], "north")
        self.assertTrue(graph["connections"][0]["bidirectional"])
        self.assertEqual(
            [(exit.name, exit.destination_room_id) for exit in self.world.get_room("hall").exits],
            [("north", "entrance")],
        )

    def test_connection_direction_can_be_changed_through_api(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        for room_id in ("entrance", "hall"):
            self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": room_id.title(), "x": 0, "y": 0},
            )
        self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "destination_room_id": "hall",
                "exit_name": "north",
            },
        )

        one_way_status, one_way = self.api.handle(
            "PATCH",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "exit_name": "north",
                "bidirectional": False,
            },
        )
        self.assertEqual(one_way_status, 200)
        self.assertFalse(one_way["bidirectional"])
        self.assertEqual(self.world.get_room("hall").exits, ())

        two_way_status, two_way = self.api.handle(
            "PATCH",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "exit_name": "north",
                "bidirectional": True,
                "return_exit_name": "south",
            },
        )
        self.assertEqual(two_way_status, 200)
        self.assertTrue(two_way["bidirectional"])
        self.assertEqual(two_way["return_exit_name"], "south")
        self.assertEqual(
            [(exit.name, exit.destination_room_id) for exit in self.world.get_room("hall").exits],
            [("south", "entrance")],
        )

        _, graph = self.api.handle("GET", "/api/areas/crypt/graph")
        self.assertEqual(len(graph["connections"]), 1)
        self.assertTrue(graph["connections"][0]["bidirectional"])
        self.assertEqual(graph["connections"][0]["return_exit_name"], "south")

    def test_connection_can_be_created_explicitly_one_way(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        for room_id in ("entrance", "hall"):
            self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": room_id.title(), "x": 0, "y": 0},
            )

        status, created = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "destination_room_id": "hall",
                "exit_name": "drop",
                "bidirectional": False,
            },
        )

        self.assertEqual(status, 201)
        self.assertFalse(created["bidirectional"])
        self.assertIsNone(created["return_exit_name"])
        self.assertEqual(self.world.get_room("hall").exits, ())

    def test_rejected_connection_does_not_appear_in_graph(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "one", "name": "One"})
        self.api.handle("POST", "/api/areas", {"id": "two", "name": "Two"})
        self.api.handle(
            "POST", "/api/areas/one/rooms", {"id": "a", "name": "A", "x": 0, "y": 0}
        )
        self.api.handle(
            "POST", "/api/areas/two/rooms", {"id": "b", "name": "B", "x": 0, "y": 0}
        )

        status, payload = self.api.handle(
            "POST",
            "/api/connections",
            {"source_room_id": "a", "destination_room_id": "b", "exit_name": "bad"},
        )

        self.assertEqual(status, 400)
        self.assertIn("different areas", payload["error"])
        _, graph = self.api.handle("GET", "/api/areas/one/graph")
        self.assertEqual(graph["connections"], [])

    def test_lists_characters_and_places_one_in_a_room(self) -> None:
        character = self.database.create_character(123, "Olof", 20)
        self.database.create_character(456, "Aria", 15)
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        self.api.handle(
            "POST",
            "/api/areas/crypt/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )

        status, characters = self.api.handle("GET", "/api/characters")
        placed_status, placed = self.api.handle(
            "PATCH",
            f"/api/characters/{character.character_id}/room",
            {"room_id": "hall"},
        )

        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in characters], ["Aria", "Olof"])
        self.assertEqual(placed_status, 200)
        self.assertEqual(placed["current_room_id"], "hall")
        _, graph = self.api.handle("GET", "/api/areas/crypt/graph")
        self.assertEqual(graph["nodes"][0]["players"][0]["name"], "Olof")

    def test_rejects_placing_an_unknown_character(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        self.api.handle(
            "POST",
            "/api/areas/crypt/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )

        status, payload = self.api.handle(
            "PATCH", "/api/characters/999/room", {"room_id": "hall"}
        )

        self.assertEqual(status, 400)
        self.assertIn("does not exist", payload["error"])

    def test_catalog_item_is_created_once_then_selected_for_a_room(self) -> None:
        character = self.database.create_character(123, "Olof", 20)
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        self.api.handle(
            "POST",
            "/api/areas/crypt/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )
        self.api.handle(
            "PATCH",
            f"/api/characters/{character.character_id}/room",
            {"room_id": "hall"},
        )

        created_status, created = self.api.handle(
            "POST",
            "/api/items",
            {
                "id": "iron_key",
                "item_type": "misc",
                "name": "Iron Key",
                "description": "Opens the crypt.",
                "rarity": "Common",
                "value": 2,
                "weight": 0,
            },
        )
        placed_status, _ = self.api.handle(
            "POST",
            "/api/rooms/hall/items",
            {"item_id": "iron_key", "quantity": 1},
        )
        self.world.take_loose_item(character.character_id, "iron_key")

        inventory = self.database.get_character_inventory(character.character_id)
        list_status, items = self.api.handle("GET", "/api/items")
        reloaded = ItemCatalog.load(self.catalog_path)
        self.assertEqual(created_status, 201)
        self.assertEqual(created["id"], "iron_key")
        self.assertEqual(placed_status, 201)
        self.assertEqual(list_status, 200)
        self.assertEqual([item["id"] for item in items], ["iron_key"])
        self.assertTrue(
            any(item.template_id == "iron_key" for item in inventory.items)
        )
        self.assertEqual(reloaded.get("iron_key").name, "Iron Key")

    def test_creating_catalog_item_migrates_matching_legacy_character_item(self) -> None:
        character = self.database.create_character(123, "Olof", 20)
        self.world.create_item("old_key", "Key", stackable=False)
        holder = InventoryHolder.character(character.character_id)
        self.world.place_item(holder, "old_key")

        status, _ = self.api.handle(
            "POST",
            "/api/items",
            {
                "id": "key",
                "item_type": "misc",
                "name": "Key",
                "rarity": "Common",
                "value": 0,
                "weight": 0,
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(self.world.inventory(holder), ())
        inventory = self.database.get_character_inventory(character.character_id)
        self.assertTrue(any(item.template_id == "key" for item in inventory.items))

    def test_room_rejects_item_that_is_not_in_catalog(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        self.api.handle(
            "POST",
            "/api/areas/crypt/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )

        status, payload = self.api.handle(
            "POST",
            "/api/rooms/hall/items",
            {"item_id": "invented_here", "quantity": 1},
        )

        self.assertEqual(status, 400)
        self.assertIn("Unknown item template", payload["error"])

    def test_readable_item_content_is_created_and_edited(self) -> None:
        created_status, created = self.api.handle(
            "POST",
            "/api/items",
            {
                "id": "bloodstained_note",
                "item_type": "readable",
                "name": "Bloodstained Note",
                "description": "A folded note stained with old blood.",
                "rarity": "Common",
                "value": 0,
                "weight": 0,
                "content": "Do not open the western gate after sunset...",
            },
        )
        updated_status, updated = self.api.handle(
            "PUT",
            "/api/items/bloodstained_note",
            {
                "item_type": "readable",
                "name": "Bloodstained Note",
                "description": "A folded note stained with old blood.",
                "rarity": "Common",
                "value": 0,
                "weight": 0,
                "content": "The western gate is already open.",
            },
        )

        self.assertEqual(created_status, 201)
        self.assertEqual(created["content"], "Do not open the western gate after sunset...")
        self.assertEqual(created["slot_cost"], 0)
        self.assertEqual(updated_status, 200)
        self.assertEqual(updated["content"], "The western gate is already open.")
        self.assertEqual(
            ItemCatalog.load(self.catalog_path).get("bloodstained_note").content,
            "The western gate is already open.",
        )


if __name__ == "__main__":
    unittest.main()
