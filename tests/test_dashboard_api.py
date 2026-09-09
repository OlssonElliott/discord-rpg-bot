import tempfile
import unittest
from pathlib import Path

from rpg_bot.dashboard_api import DashboardAPI
from rpg_bot.database import Database
from rpg_bot.world_service import WorldService


class DashboardAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_directory.name) / "dashboard.db")
        self.database.initialize()
        self.world = WorldService(self.database)
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
        self.assertEqual(graph["connections"][0]["exit_name"], "north")

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


if __name__ == "__main__":
    unittest.main()
