from io import BytesIO
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from rpg_bot.dashboard.api import DashboardAPI
from rpg_bot.database import Database
from rpg_bot.inventory import ItemCatalog
from rpg_bot.media.portraits import CharacterPortraitStore
from rpg_bot.media.room_images import RoomImageStore
from rpg_bot.world import InventoryHolder
from rpg_bot.world.service import WorldService


class DashboardAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_directory.name) / "dashboard.db")
        self.database.initialize()
        self.catalog_path = Path(self.temp_directory.name) / "items.json"
        self.catalog_path.write_text("[]\n", encoding="utf-8")
        self.world = WorldService(self.database, ItemCatalog.load(self.catalog_path))
        self.room_images = RoomImageStore(
            Path(self.temp_directory.name) / "room_images"
        )
        self.portraits = CharacterPortraitStore(
            Path(self.temp_directory.name) / "characters"
        )
        self.api = DashboardAPI(
            self.world,
            self.room_images,
            portraits=self.portraits,
            guild_id=44,
        )

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
                "connection_type": "door",
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
        self.assertEqual(graph["connections"][0]["connection_type"], "door")
        self.assertEqual(
            [(exit.name, exit.destination_room_id) for exit in self.world.get_room("hall").exits],
            [("north", "entrance")],
        )

    def test_room_features_can_be_managed_through_api(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        self.api.handle(
            "POST",
            "/api/areas/crypt/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )

        create_status, created = self.api.handle(
            "POST",
            "/api/rooms/hall/features",
            {
                "id": "oak_table",
                "name": "Heavy Oak Table",
                "feature_type": "furniture",
                "description": "A broad table covered in old knife marks.",
            },
        )
        list_status, listed = self.api.handle("GET", "/api/rooms/hall/features")
        get_status, fetched = self.api.handle("GET", "/api/room-features/oak_table")
        graph_status, graph = self.api.handle("GET", "/api/areas/crypt/graph")

        self.assertEqual(create_status, 201)
        self.assertEqual(created["feature_type"], "furniture")
        self.assertEqual(list_status, 200)
        self.assertEqual([feature["id"] for feature in listed], ["oak_table"])
        self.assertEqual(get_status, 200)
        self.assertEqual(fetched["description"], "A broad table covered in old knife marks.")
        self.assertEqual(graph_status, 200)
        self.assertEqual(graph["nodes"][0]["room_features"], [created])

        update_status, updated = self.api.handle(
            "PATCH",
            "/api/room-features/oak_table",
            {
                "name": "Scarred Oak Table",
                "feature_type": "structure",
                "description": "The table has been bolted to the floor.",
            },
        )

        self.assertEqual(update_status, 200)
        self.assertEqual(updated["name"], "Scarred Oak Table")
        self.assertEqual(updated["feature_type"], "structure")

        delete_status, deleted = self.api.handle(
            "DELETE", "/api/room-features/oak_table"
        )
        missing_status, _ = self.api.handle("GET", "/api/room-features/oak_table")
        _, graph_after_delete = self.api.handle("GET", "/api/areas/crypt/graph")

        self.assertEqual(delete_status, 200)
        self.assertEqual(deleted, {"deleted": "oak_table"})
        self.assertEqual(missing_status, 404)
        self.assertEqual(graph_after_delete["nodes"][0]["room_features"], [])

    def test_combat_scene_can_be_controlled_through_dashboard_api(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "keep", "name": "Keep"})
        self.api.handle(
            "POST",
            "/api/areas/keep/rooms",
            {"id": "hall", "name": "Guard Hall", "x": 0, "y": 0},
        )
        for feature_id, name in (
            ("pillar", "Stone Pillar"),
            ("table", "Oak Table"),
        ):
            status, _ = self.api.handle(
                "POST",
                "/api/rooms/hall/features",
                {
                    "id": feature_id,
                    "name": name,
                    "feature_type": "structure",
                    "description": "",
                },
            )
            self.assertEqual(status, 201)
        status, _ = self.api.handle(
            "POST",
            "/api/rooms/hall/entities",
            {
                "id": "bandit",
                "name": "Bandit",
                "kind": "enemy",
            },
        )
        self.assertEqual(status, 201)

        status, state = self.api.handle(
            "POST",
            "/api/combat",
            {"room_id": "hall"},
        )
        self.assertEqual(status, 201)
        scene = state["scene"]
        self.assertEqual(scene["room_name"], "Guard Hall")
        self.assertEqual(
            {landmark["id"] for landmark in scene["landmarks"]},
            {
                "room:center",
                "room:corner:nw",
                "room:corner:ne",
                "room:corner:sw",
                "room:corner:se",
                "feature:pillar",
                "feature:table",
            },
        )
        center = next(
            landmark
            for landmark in scene["landmarks"]
            if landmark["id"] == "room:center"
        )
        pillar = next(
            landmark
            for landmark in scene["landmarks"]
            if landmark["id"] == "feature:pillar"
        )
        self.assertEqual(center["cover"], "none")
        self.assertTrue(center["auto_connect"])
        self.assertEqual(pillar["cover"], "half")
        self.assertTrue(pillar["auto_connect"])
        self.assertEqual(
            [(combatant["kind"], combatant["name"]) for combatant in scene["combatants"]],
            [("enemy", "Bandit")],
        )
        self.assertEqual(
            [entry["event_type"] for entry in scene["log_entries"][:2]],
            ["combat_started", "turn_started"],
        )

        inspect_legacy_status, legacy_bandit = self.api.handle(
            "GET",
            "/api/combat/combatants/enemy/bandit/inspect",
        )
        self.assertEqual(inspect_legacy_status, 200)
        self.assertEqual(legacy_bandit["name"], "Bandit")
        self.assertIsNone(legacy_bandit["hp"])
        self.assertEqual(legacy_bandit["attributes"], {})

        status, positioned = self.api.handle(
            "PATCH",
            "/api/combat/landmarks/feature:pillar",
            {"x": 0.25, "y": 0.35},
        )
        self.assertEqual(status, 200)
        pillar = next(
            landmark
            for landmark in positioned["scene"]["landmarks"]
            if landmark["id"] == "feature:pillar"
        )
        self.assertEqual((pillar["x"], pillar["y"]), (0.25, 0.35))

        status, no_cover = self.api.handle(
            "PATCH",
            "/api/combat/landmarks/feature:pillar",
            {"cover": "none"},
        )
        self.assertEqual(status, 200)
        pillar = next(
            landmark
            for landmark in no_cover["scene"]["landmarks"]
            if landmark["id"] == "feature:pillar"
        )
        self.assertEqual(pillar["cover"], "none")

        invalid_move_status, _ = self.api.handle(
            "PATCH",
            "/api/combat/combatants/enemy/bandit",
            {"landmark_id": "feature:pillar", "relation": "behind"},
        )
        self.assertEqual(invalid_move_status, 400)

        status, with_cover = self.api.handle(
            "PATCH",
            "/api/combat/landmarks/feature:pillar",
            {"cover": "full", "auto_connect": False},
        )
        self.assertEqual(status, 200)
        pillar = next(
            landmark
            for landmark in with_cover["scene"]["landmarks"]
            if landmark["id"] == "feature:pillar"
        )
        self.assertEqual(pillar["cover"], "full")
        self.assertFalse(pillar["auto_connect"])

        status, routed = self.api.handle(
            "PUT",
            "/api/combat/routes",
            {
                "source_landmark_id": "feature:pillar",
                "destination_landmark_id": "feature:table",
                "distance": "close",
                "obstacle": "Fallen rubble",
                "blocked": False,
            },
        )
        self.assertEqual(status, 200)
        feature_route = next(
            route
            for route in routed["scene"]["routes"]
            if {
                route["source_landmark_id"],
                route["destination_landmark_id"],
            }
            == {
                "feature:pillar",
                "feature:table",
            }
        )
        self.assertEqual(feature_route["obstacle"], "Fallen rubble")

        delete_route_status, disconnected = self.api.handle(
            "DELETE",
            "/api/combat/routes",
            {
                "source_landmark_id": "feature:pillar",
                "destination_landmark_id": "feature:table",
            },
        )
        self.assertEqual(delete_route_status, 200)
        self.assertEqual(len(disconnected["scene"]["routes"]), 4)
        self.assertEqual(
            {
                frozenset(
                    (
                        route["source_landmark_id"],
                        route["destination_landmark_id"],
                    )
                )
                for route in disconnected["scene"]["routes"]
            },
            {
                frozenset(("room:center", "room:corner:nw")),
                frozenset(("room:center", "room:corner:ne")),
                frozenset(("room:center", "room:corner:sw")),
                frozenset(("room:center", "room:corner:se")),
            },
        )

        add_landmark_status, with_landmark = self.api.handle(
            "POST",
            "/api/combat/landmarks",
            {
                "name": "Broken balcony",
                "description": "A raised ledge.",
            },
        )
        self.assertEqual(add_landmark_status, 201)
        custom = next(
            landmark
            for landmark in with_landmark["scene"]["landmarks"]
            if landmark["feature_type"] == "custom"
        )
        self.assertEqual(custom["name"], "Broken balcony")
        self.assertIsNotNone(custom["x"])
        self.assertIsNotNone(custom["y"])

        remove_landmark_status, without_landmark = self.api.handle(
            "DELETE",
            f"/api/combat/landmarks/{custom['id']}",
        )
        self.assertEqual(remove_landmark_status, 200)
        self.assertNotIn(
            custom["id"],
            {
                landmark["id"]
                for landmark in without_landmark["scene"]["landmarks"]
            },
        )

        status, moved = self.api.handle(
            "PATCH",
            "/api/combat/combatants/enemy/bandit",
            {"landmark_id": "feature:pillar", "relation": "behind"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(moved["scene"]["combatants"][0]["landmark_id"], "feature:pillar")
        self.assertEqual(moved["scene"]["combatants"][0]["relation"], "behind")

        add_enemy_status, reinforced = self.api.handle(
            "POST",
            "/api/combat/enemies",
            {
                "template_id": "core_goblin_raider",
                "landmark_id": "feature:table",
                "quantity": 2,
            },
        )
        self.assertEqual(add_enemy_status, 201)
        goblins = [
            combatant
            for combatant in reinforced["scene"]["combatants"]
            if combatant["name"] == "Goblin Raider"
        ]
        self.assertEqual(len(goblins), 2)
        self.assertEqual(
            {goblin["landmark_id"] for goblin in goblins},
            {"feature:table"},
        )
        self.assertNotEqual(goblins[0]["source_id"], goblins[1]["source_id"])
        self.assertIsNotNone(
            self.world.get_enemy(goblins[0]["source_id"])
        )

        inspect_status, inspected = self.api.handle(
            "GET",
            f"/api/combat/combatants/enemy/{goblins[1]['source_id']}/inspect",
        )
        self.assertEqual(inspect_status, 200)
        self.assertEqual(inspected["name"], "Goblin Raider")
        self.assertEqual(inspected["hp"], inspected["max_hp"])
        self.assertEqual(inspected["attributes"]["insight"], 1)
        self.assertEqual(inspected["enemy"]["template_name"], "Goblin Raider")
        self.assertEqual(
            inspected["enemy"]["attack_profile"],
            "Jagged blade or shortbow",
        )

        remove_enemy_status, reduced = self.api.handle(
            "DELETE",
            f"/api/combat/combatants/enemy/{goblins[0]['source_id']}",
        )
        self.assertEqual(remove_enemy_status, 200)
        self.assertNotIn(
            goblins[0]["source_id"],
            {
                combatant["source_id"]
                for combatant in reduced["scene"]["combatants"]
            },
        )
        self.assertIsNotNone(
            self.world.get_enemy(goblins[0]["source_id"])
        )

        remaining_goblin = goblins[1]
        initiative_status, initiative_state = self.api.handle(
            "PATCH",
            f"/api/combat/initiative/enemy/{remaining_goblin['source_id']}",
            {"initiative_score": 30},
        )
        self.assertEqual(initiative_status, 200)
        edited_goblin = next(
            combatant
            for combatant in initiative_state["scene"]["combatants"]
            if combatant["source_id"] == remaining_goblin["source_id"]
        )
        self.assertEqual(edited_goblin["initiative_score"], 30)

        jump_status, jumped = self.api.handle(
            "PUT",
            "/api/combat/turn",
            {
                "kind": "enemy",
                "source_id": remaining_goblin["source_id"],
            },
        )
        self.assertEqual(jump_status, 200)
        self.assertEqual(
            jumped["scene"]["current_turn_source_id"],
            remaining_goblin["source_id"],
        )
        self.assertTrue(
            next(
                combatant
                for combatant in jumped["scene"]["combatants"]
                if combatant["source_id"] == remaining_goblin["source_id"]
            )["is_current_turn"]
        )

        next_status, advanced = self.api.handle(
            "POST",
            "/api/combat/turn/next",
        )
        self.assertEqual(next_status, 200)
        self.assertNotEqual(
            advanced["scene"]["current_turn_source_id"],
            remaining_goblin["source_id"],
        )

        previous_status, restored = self.api.handle(
            "POST",
            "/api/combat/turn/previous",
        )
        self.assertEqual(previous_status, 200)
        self.assertEqual(
            restored["scene"]["current_turn_source_id"],
            remaining_goblin["source_id"],
        )

        status, ended = self.api.handle("DELETE", "/api/combat")
        self.assertEqual(status, 200)
        self.assertIsNone(ended["scene"])

    def test_character_workspace_can_inspect_and_edit_character(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "keep", "name": "Keep"})
        self.api.handle(
            "POST",
            "/api/areas/keep/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )
        character = self.database.create_character(
            77,
            "Mira",
            18,
            race="Human",
            attributes={
                "Strength": 12,
                "Dexterity": 10,
                "Arcana": 9,
                "Vitality": 13,
                "Insight": 14,
                "Personality": 11,
            },
            skills={"Perception": 2},
        )
        assert character.character_id is not None
        self.world.place_character(character.character_id, "hall")

        list_status, listed = self.api.handle("GET", "/api/characters")
        inspect_status, inspected = self.api.handle(
            "GET",
            f"/api/characters/{character.character_id}",
        )

        self.assertEqual(list_status, 200)
        self.assertEqual(listed[0]["name"], "Mira")
        self.assertEqual(listed[0]["current_room_name"], "Hall")
        self.assertEqual(listed[0]["status"], "active")
        self.assertEqual(inspect_status, 200)
        self.assertEqual(inspected["attributes"]["Insight"], 14)
        self.assertEqual(inspected["skills"]["Perception"], 2)

        update_status, updated = self.api.handle(
            "PATCH",
            f"/api/characters/{character.character_id}",
            {
                "name": "Mira Thorn",
                "hp": -3,
                "max_hp": 20,
                "status": "downed",
                "failed_death_saves": 1,
                "stance": "prone",
                "race": "Human",
                "lineage": "Northborn",
                "age": "29",
                "gender": "Female",
                "current_room_id": "hall",
                "attributes": {
                    "Strength": 13,
                    "Dexterity": 11,
                    "Arcana": 9,
                    "Vitality": 15,
                    "Insight": 14,
                    "Personality": 10,
                },
                "skills": {
                    "Perception": 3,
                    "Survival": 1,
                },
                "wallet": {
                    "copper": 8,
                    "silver": 4,
                    "gold": 2,
                },
            },
        )

        self.assertEqual(update_status, 200)
        self.assertEqual(updated["name"], "Mira Thorn")
        self.assertEqual((updated["hp"], updated["max_hp"]), (-3, 20))
        self.assertEqual(updated["status"], "downed")
        self.assertEqual(updated["failed_death_saves"], 1)
        self.assertEqual(updated["stance"], "prone")
        self.assertEqual(updated["attributes"]["Vitality"], 15)
        self.assertEqual(updated["skills"]["Survival"], 1)
        self.assertEqual(updated["wallet"], {
            "copper": 8,
            "silver": 4,
            "gold": 2,
        })

    def test_character_workspace_can_manage_inventory(self) -> None:
        character = self.database.create_character(77, "Mira", 18)
        assert character.character_id is not None
        self.world.create_item_template(
            {
                "id": "test_blade",
                "item_type": "weapon",
                "name": "Test Blade",
                "rarity": "common",
                "value": 5,
                "description": "A testing weapon.",
                "weight": 1,
                "grip": "one_handed",
                "durability": 6,
                "damage_parts": [
                    {"amount": 6, "damage_type": "slash"}
                ],
            }
        )

        add_status, added = self.api.handle(
            "POST",
            f"/api/characters/{character.character_id}/items",
            {"template_id": "test_blade", "quantity": 1},
        )
        self.assertEqual(add_status, 201)
        item = next(
            item
            for item in added["inventory"]
            if item["template_id"] == "test_blade"
        )

        edit_status, edited = self.api.handle(
            "PATCH",
            (
                f"/api/characters/{character.character_id}"
                f"/items/{item['id']}"
            ),
            {
                "quantity": 2,
                "durability": 4,
                "equipped_slot": "main_hand",
            },
        )
        self.assertEqual(edit_status, 200)
        edited_item = next(
            candidate
            for candidate in edited["inventory"]
            if candidate["id"] == item["id"]
        )
        self.assertEqual(edited_item["quantity"], 2)
        self.assertEqual(edited_item["durability"], 4)
        self.assertEqual(edited_item["equipped_slot"], "main_hand")

        delete_status, after_delete = self.api.handle(
            "DELETE",
            (
                f"/api/characters/{character.character_id}"
                f"/items/{item['id']}"
            ),
        )
        self.assertEqual(delete_status, 200)
        self.assertFalse(
            any(
                candidate["id"] == item["id"]
                for candidate in after_delete["inventory"]
            )
        )

    def test_character_workspace_can_upload_portrait(self) -> None:
        character = self.database.create_character(77, "Mira", 18)
        assert character.character_id is not None
        image = Image.new("RGB", (320, 240), "white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")

        status, updated = self.api.upload_character_portrait(
            character.character_id,
            buffer.getvalue(),
        )

        self.assertEqual(status, 200)
        self.assertIsNotNone(updated["portrait_url"])
        self.assertIsNotNone(
            self.api.character_portrait_path(character.character_id)
        )

    def test_character_combatant_can_be_inspected(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "keep", "name": "Keep"})
        self.api.handle(
            "POST",
            "/api/areas/keep/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )
        character = self.database.create_character(
            77,
            "Mira",
            18,
            race="Human",
            attributes={
                "Strength": 12,
                "Dexterity": 10,
                "Arcana": 9,
                "Vitality": 13,
                "Insight": 14,
                "Personality": 11,
            },
            skills={"Perception": 2},
        )
        assert character.character_id is not None
        self.world.place_character(character.character_id, "hall")
        self.api.handle("POST", "/api/combat", {"room_id": "hall"})

        status, inspected = self.api.handle(
            "GET",
            f"/api/combat/combatants/character/{character.character_id}/inspect",
        )

        self.assertEqual(status, 200)
        self.assertEqual(inspected["name"], "Mira")
        self.assertEqual((inspected["hp"], inspected["max_hp"]), (18, 18))
        self.assertEqual(inspected["attributes"]["Insight"], 14)
        self.assertEqual(inspected["skills"]["Perception"], 2)
        self.assertIsNotNone(inspected["wallet"])
        self.assertIsInstance(inspected["inventory"], list)
        self.assertIsInstance(inspected["equipment"], list)

    def test_combat_scene_exposes_linked_room_door_landmark(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "gatehouse", "name": "Gatehouse"})
        for room_id, name in (("hall", "Hall"), ("yard", "Yard")):
            self.api.handle(
                "POST",
                "/api/areas/gatehouse/rooms",
                {"id": room_id, "name": name, "x": 0, "y": 0},
            )
        connection_status, connection = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "hall",
                "destination_room_id": "yard",
                "exit_name": "north gate",
                "return_exit_name": "south gate",
                "connection_type": "door",
            },
        )
        self.assertEqual(connection_status, 201)

        status, state = self.api.handle(
            "POST",
            "/api/combat",
            {"room_id": "hall"},
        )

        self.assertEqual(status, 201)
        door = next(
            landmark
            for landmark in state["scene"]["landmarks"]
            if landmark["feature_type"] == "door"
        )
        self.assertEqual(door["name"], "Door: north gate")
        self.assertEqual(
            door["source_connection_id"],
            connection["connection_id"],
        )
        self.assertIn("Yard", door["description"])

    def test_room_feature_templates_are_reusable_and_independent(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        for room_id in ("hall", "vault"):
            self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": room_id.title(), "x": 0, "y": 0},
            )

        create_status, template = self.api.handle(
            "POST",
            "/api/room-feature-templates",
            {
                "id": "oak_table",
                "name": "Heavy Oak Table",
                "feature_type": "furniture",
                "description": "A broad table covered in old knife marks.",
            },
        )
        list_status, templates = self.api.handle(
            "GET", "/api/room-feature-templates"
        )

        self.assertEqual(create_status, 201)
        self.assertEqual(list_status, 200)
        self.assertEqual([item["id"] for item in templates], ["oak_table"])

        placed = []
        for room_id in ("hall", "vault"):
            status, feature = self.api.handle(
                "POST",
                f"/api/rooms/{room_id}/features",
                {
                    "id": f"{room_id}_oak_table",
                    "name": template["name"],
                    "feature_type": template["feature_type"],
                    "description": template["description"],
                },
            )
            self.assertEqual(status, 201)
            placed.append(feature)

        update_status, updated = self.api.handle(
            "PATCH",
            "/api/room-feature-templates/oak_table",
            {
                "name": "Polished Oak Table",
                "feature_type": "decoration",
                "description": "Restored for a noble hall.",
            },
        )
        _, hall_feature = self.api.handle(
            "GET", "/api/room-features/hall_oak_table"
        )
        delete_status, deleted = self.api.handle(
            "DELETE", "/api/room-feature-templates/oak_table"
        )
        _, vault_feature = self.api.handle(
            "GET", "/api/room-features/vault_oak_table"
        )

        self.assertEqual(update_status, 200)
        self.assertEqual(updated["name"], "Polished Oak Table")
        self.assertEqual(hall_feature, placed[0])
        self.assertEqual(delete_status, 200)
        self.assertEqual(deleted, {"deleted": "oak_table"})
        self.assertEqual(vault_feature, placed[1])

    def test_enemy_templates_create_independent_persistent_room_instances(self) -> None:
        self.api.handle(
            "POST",
            "/api/areas",
            {"id": "crypt", "name": "Crypt"},
        )
        self.api.handle(
            "POST",
            "/api/areas/crypt/rooms",
            {
                "id": "hall",
                "name": "Hall",
                "x": 0,
                "y": 0,
            },
        )

        item_status, _ = self.api.handle(
            "POST",
            "/api/items",
            {
                "id": "rusty_sword",
                "name": "Rusty Sword",
                "item_type": "weapon",
                "damage": 3,
            },
        )

        template_status, template = self.api.handle(
            "POST",
            "/api/enemy-templates",
            {
                "id": "skeleton_warrior",
                "name": "Skeleton Warrior",
                "race": "Undead",
                "difficulty_level": 2,
                "strength": 3,
                "dexterity": 1,
                "vitality": 3,
                "max_hp": 10,
                "armor": 1,
                "attack_dc": 14,
                "defense_dc": 11,
                "damage": "1d6",
                "attack_profile": "Heavy sword swing",
                "special_ability": "Ignores ordinary fear.",
                "typical_behaviour": "Slow and relentless.",
                "main_hand_item_id": "rusty_sword",
            },
        )

        first_status, first = self.api.handle(
            "POST",
            "/api/rooms/hall/enemies",
            {"template_id": template["id"]},
        )
        second_status, second = self.api.handle(
            "POST",
            "/api/rooms/hall/enemies",
            {"template_id": template["id"]},
        )
        graph_status, graph = self.api.handle(
            "GET",
            "/api/areas/crypt/graph",
        )

        self.assertEqual(item_status, 201)
        self.assertEqual(template_status, 201)
        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(
            (first["current_hp"], first["max_hp"]),
            (10, 10),
        )
        self.assertEqual(
            (second["current_hp"], second["max_hp"]),
            (10, 10),
        )
        self.assertEqual(graph_status, 200)
        self.assertEqual(
            {
                enemy["id"]
                for enemy in graph["nodes"][0]["enemies"]
            },
            {first["id"], second["id"]},
        )
        self.assertEqual(
            [
                stack.item.id
                for stack in self.world.inventory(
                    InventoryHolder.entity(first["id"])
                )
            ],
            ["rusty_sword"],
        )

        update_status, updated = self.api.handle(
            "PATCH",
            f"/api/enemies/{first['id']}",
            {"current_hp": 3},
        )
        _, untouched = self.api.handle(
            "GET",
            f"/api/enemies/{second['id']}",
        )

        self.assertEqual(update_status, 200)
        self.assertEqual(updated["current_hp"], 3)
        self.assertEqual(untouched["current_hp"], 10)

        reopened = Database(self.database.path)
        reopened.initialize()
        persisted = reopened.get_enemy_instance(first["id"])
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.current_hp, 3)

        delete_in_use_status, _ = self.api.handle(
            "DELETE",
            "/api/enemy-templates/skeleton_warrior",
        )
        self.assertEqual(delete_in_use_status, 400)

        self.api.handle(
            "DELETE",
            f"/api/enemies/{first['id']}",
        )
        self.api.handle(
            "DELETE",
            f"/api/enemies/{second['id']}",
        )
        delete_status, deleted = self.api.handle(
            "DELETE",
            "/api/enemy-templates/skeleton_warrior",
        )
        self.assertEqual(delete_status, 200)
        self.assertEqual(
            deleted,
            {"deleted": "skeleton_warrior"},
        )

    def test_basic_enemy_templates_are_seeded_once_and_can_be_changed_or_deleted(self) -> None:
        status, templates = self.api.handle(
            "GET",
            "/api/enemy-templates",
        )
        self.assertEqual(status, 200)
        self.assertTrue(
            {
                "core_goblin_raider",
                "core_bandit",
                "core_skeleton_warrior",
                "core_bone_hound",
                "core_cultist",
                "core_swamp_troll",
            }.issubset({template["id"] for template in templates})
        )

        update_status, updated = self.api.handle(
            "PUT",
            "/api/enemy-templates/core_bandit",
            {
                "name": "Road Bandit",
                "max_hp": 11,
            },
        )
        self.assertEqual(update_status, 200)
        self.assertEqual(updated["name"], "Road Bandit")
        self.assertEqual(updated["max_hp"], 11)

        delete_status, _ = self.api.handle(
            "DELETE",
            "/api/enemy-templates/core_bone_hound",
        )
        self.assertEqual(delete_status, 200)

        reopened = Database(self.database.path)
        reopened.initialize()
        self.assertIsNone(
            reopened.get_enemy_template("core_bone_hound")
        )
        persisted = reopened.get_enemy_template("core_bandit")
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.name, "Road Bandit")
        self.assertEqual(persisted.max_hp, 11)

    def test_room_image_can_be_uploaded_replaced_persisted_and_removed(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        self.api.handle(
            "POST",
            "/api/areas/crypt/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )

        first_status, first = self.api.upload_room_image(
            "hall", self._image_bytes("red"), "image/png"
        )
        first_key = self.world.get_room("hall").scene_image_path
        first_path = self.room_images.path_for(first_key)

        self.assertEqual(first_status, 200)
        self.assertIn("/api/rooms/hall/image?version=", first["room_image_url"])
        self.assertIsNotNone(first_path)
        reopened = Database(self.database.path)
        reopened.initialize()
        self.assertEqual(reopened.get_room("hall").scene_image_path, first_key)

        second_status, _ = self.api.upload_room_image(
            "hall", self._image_bytes("blue"), "image/jpeg"
        )
        second_key = self.world.get_room("hall").scene_image_path

        self.assertEqual(second_status, 200)
        self.assertNotEqual(second_key, first_key)
        self.assertIsNone(self.room_images.path_for(first_key))
        self.assertIsNotNone(self.room_images.path_for(second_key))

        remove_status, removed = self.api.handle(
            "DELETE", "/api/rooms/hall/image"
        )

        self.assertEqual(remove_status, 200)
        self.assertIsNone(removed["room_image_url"])
        self.assertIsNone(self.world.get_room("hall").scene_image_path)
        self.assertIsNone(self.room_images.path_for(second_key))

    def test_room_image_rejects_invalid_type_and_content(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        self.api.handle(
            "POST",
            "/api/areas/crypt/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )

        wrong_type_status, wrong_type = self.api.upload_room_image(
            "hall", self._image_bytes("red"), "text/plain"
        )
        fake_image_status, fake_image = self.api.upload_room_image(
            "hall", b"not an image", "image/png"
        )

        self.assertEqual(wrong_type_status, 400)
        self.assertIn("PNG, JPEG, or WebP", wrong_type["error"])
        self.assertEqual(fake_image_status, 400)
        self.assertIn("not a readable", fake_image["error"])
        self.assertIsNone(self.world.get_room("hall").scene_image_path)

    @staticmethod
    def _image_bytes(colour: str) -> bytes:
        output = BytesIO()
        image_format = "JPEG" if colour == "blue" else "PNG"
        Image.new("RGB", (640, 360), colour).save(output, format=image_format)
        return output.getvalue()

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

    def test_connection_map_type_can_be_changed_through_api(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        for room_id in ("entrance", "hall"):
            self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": room_id.title(), "x": 0, "y": 0},
            )
        _, created = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "destination_room_id": "hall",
                "exit_name": "north",
                "connection_type": "hallway",
            },
        )
        self.assertEqual(created["connection_type"], "hallway")
        self.assertFalse(created["has_lock"])
        self.assertFalse(created["is_locked"])
        self.assertIsNone(created["unlock_difficulty"])

        status, updated = self.api.handle(
            "PATCH",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "exit_name": "north",
                "connection_type": "door",
                "is_locked": True,
                "unlock_difficulty": 17,
                "bidirectional": True,
                "return_exit_name": "south",
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(updated["connection_type"], "door")
        self.assertTrue(updated["has_lock"])
        self.assertTrue(updated["is_locked"])
        self.assertEqual(updated["unlock_difficulty"], 17)
        _, graph = self.api.handle("GET", "/api/areas/crypt/graph")
        self.assertEqual(graph["connections"][0]["connection_type"], "door")
        self.assertTrue(graph["connections"][0]["has_lock"])
        self.assertTrue(graph["connections"][0]["is_locked"])
        self.assertEqual(graph["connections"][0]["unlock_difficulty"], 17)

        _, broken = self.api.handle(
            "PATCH",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "exit_name": "north",
                "connection_type": "door",
                "has_lock": True,
                "is_locked": False,
                "is_broken": True,
                "bidirectional": True,
                "return_exit_name": "south",
            },
        )
        self.assertTrue(broken["is_broken"])
        self.assertFalse(broken["is_locked"])
        _, graph = self.api.handle("GET", "/api/areas/crypt/graph")
        self.assertTrue(graph["connections"][0]["is_broken"])

        _, opened = self.api.handle(
            "PATCH",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "exit_name": "north",
                "connection_type": "door",
                "is_open": True,
                "bidirectional": True,
                "return_exit_name": "south",
            },
        )
        self.assertTrue(opened["is_open"])
        _, graph = self.api.handle("GET", "/api/areas/crypt/graph")
        self.assertTrue(graph["connections"][0]["is_open"])

    def test_hallway_cannot_be_locked(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        for room_id in ("entrance", "hall"):
            self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": room_id.title(), "x": 0, "y": 0},
            )

        status, error = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "destination_room_id": "hall",
                "exit_name": "north",
                "connection_type": "hallway",
                "is_locked": True,
                "unlock_difficulty": 12,
            },
        )

        self.assertEqual(status, 400)
        self.assertIn("Only door", error["error"])

    def test_door_and_hallway_traps_can_be_configured(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        for room_id in ("entrance", "hall", "vault"):
            self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": room_id.title(), "x": 0, "y": 0},
            )

        _, door = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "destination_room_id": "hall",
                "exit_name": "north",
                "connection_type": "door",
                "has_trap": True,
                "trap_state": "armed",
                "trap_detection_difficulty": 16,
                "trap_disarm_difficulty": 18,
                "trap_damage_type": "fire",
                "trap_damage": 8,
            },
        )
        _, hallway = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "hall",
                "destination_room_id": "vault",
                "exit_name": "east",
                "connection_type": "hallway",
                "has_trap": True,
                "trap_detection_difficulty": 12,
                "trap_disarm_difficulty": 14,
                "trap_damage_type": "poison",
                "trap_damage": 5,
            },
        )

        self.assertEqual(
            (door["has_trap"], door["trap_state"], door["trap_detection_difficulty"], door["trap_disarm_difficulty"], door["trap_damage_type"], door["trap_damage"]),
            (True, "armed", 16, 18, "fire", 8),
        )
        self.assertEqual(hallway["trap_damage_type"], "poison")
        _, graph = self.api.handle("GET", "/api/areas/crypt/graph")
        traps = {item["exit_name"]: item for item in graph["connections"]}
        self.assertEqual(traps["north"]["trap_damage"], 8)
        self.assertEqual(traps["east"]["trap_detection_difficulty"], 12)
        self.assertEqual(traps["east"]["trap_disarm_difficulty"], 14)

        _, updated = self.api.handle(
            "PATCH",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "exit_name": "north",
                "connection_type": "door",
                "has_trap": True,
                "trap_state": "disarmed",
                "trap_detection_difficulty": 16,
                "trap_disarm_difficulty": 20,
                "trap_damage_type": "fire",
                "trap_damage": 8,
                "bidirectional": True,
                "return_exit_name": "north",
            },
        )
        self.assertEqual(updated["trap_state"], "disarmed")
        self.assertEqual(updated["trap_disarm_difficulty"], 20)
        _, graph = self.api.handle("GET", "/api/areas/crypt/graph")
        self.assertEqual(graph["connections"][0]["trap_state"], "disarmed")
        self.assertEqual(graph["connections"][0]["trap_disarm_difficulty"], 20)

    def test_trap_configuration_is_validated(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        for room_id in ("entrance", "hall"):
            self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": room_id.title(), "x": 0, "y": 0},
            )
        status, error = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "destination_room_id": "hall",
                "exit_name": "north",
                "has_trap": True,
                "trap_detection_difficulty": 31,
                "trap_damage_type": "fire",
                "trap_damage": 2,
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("difficulty", error["error"])

        status, error = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "destination_room_id": "hall",
                "exit_name": "south",
                "has_trap": True,
                "trap_detection_difficulty": 10,
                "trap_disarm_difficulty": 31,
                "trap_damage_type": "fire",
                "trap_damage": 2,
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("disarm difficulty", error["error"])

    def test_trap_damage_type_accepts_legacy_capitalization(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        for room_id in ("entrance", "hall"):
            self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": room_id.title(), "x": 0, "y": 0},
            )

        status, connection = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "entrance",
                "destination_room_id": "hall",
                "exit_name": "north",
                "has_trap": True,
                "trap_damage_type": " Physical ",
                "trap_detection_difficulty": 10,
                "trap_damage": 1,
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(connection["trap_damage_type"], "physical")

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

    def test_connection_reports_exit_name_collision_separately_from_room_pair(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        for room_id in ("start", "next", "long_hall"):
            self.api.handle(
                "POST",
                "/api/areas/crypt/rooms",
                {"id": room_id, "name": room_id, "x": 0, "y": 0},
            )
        self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "start",
                "destination_room_id": "next",
                "exit_name": "passage",
            },
        )

        collision_status, collision = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "long_hall",
                "destination_room_id": "next",
                "exit_name": "east",
                "return_exit_name": "passage",
            },
        )
        self.assertEqual(collision_status, 400)
        self.assertIn(
            "destination already has an exit named 'passage'",
            collision["error"],
        )

        status, created = self.api.handle(
            "POST",
            "/api/connections",
            {
                "source_room_id": "long_hall",
                "destination_room_id": "next",
                "exit_name": "east",
                "return_exit_name": "west",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["exit_name"], "east")
        self.assertEqual(created["return_exit_name"], "west")

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

    def test_tool_item_can_be_created(self) -> None:
        status, created = self.api.handle(
            "POST",
            "/api/items",
            {
                "id": "fine_lockpicks",
                "item_type": "tool",
                "name": "Fine Lockpicks",
                "description": "Tools for delicate locks.",
                "rarity": "Uncommon",
                "value": 30,
                "weight": 0,
                "slot_cost": 1,
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(created["item_type"], "tool")
        self.assertFalse(created["stackable"])

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

    def test_room_items_enemies_and_containers_can_be_removed(self) -> None:
        self.api.handle("POST", "/api/areas", {"id": "crypt", "name": "Crypt"})
        self.api.handle(
            "POST",
            "/api/areas/crypt/rooms",
            {"id": "hall", "name": "Hall", "x": 0, "y": 0},
        )
        self.api.handle(
            "POST",
            "/api/items",
            {
                "id": "lockpicks",
                "item_type": "tool",
                "name": "Lockpicks",
                "rarity": "Common",
                "value": 15,
                "weight": 0,
            },
        )
        self.api.handle(
            "POST", "/api/rooms/hall/items", {"item_id": "lockpicks", "quantity": 1}
        )
        for entity_id, kind in (("rat", "enemy"), ("chest", "container")):
            self.api.handle(
                "POST",
                "/api/rooms/hall/entities",
                {"id": entity_id, "name": entity_id.title(), "kind": kind},
            )

        item_status, _ = self.api.handle(
            "DELETE", "/api/rooms/hall/items/lockpicks"
        )
        enemy_status, _ = self.api.handle(
            "DELETE", "/api/rooms/hall/entities/rat"
        )
        container_status, _ = self.api.handle(
            "DELETE", "/api/rooms/hall/entities/chest"
        )

        room = self.world.get_room("hall")
        self.assertEqual((item_status, enemy_status, container_status), (200, 200, 200))
        self.assertEqual(room.loose_items, ())
        self.assertEqual(room.enemies, ())
        self.assertEqual(room.containers, ())

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
