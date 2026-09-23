import tempfile
import unittest
from pathlib import Path

from rpg_bot.world.containers import ContainerType
from rpg_bot.database import Database
from rpg_bot.world.dungeon import ConnectionType
from rpg_bot.world import EntityKind, InventoryHolder
from rpg_bot.world.service import WorldService


class ContainerSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_directory.name) / "world.db")
        self.database.initialize()
        self.world = WorldService(self.database)
        self.area = self.world.create_area("vault", "Old Vault")
        self.room_a = self.world.create_room("vault_a", self.area.id, "Vault A")
        self.room_b = self.world.create_room("vault_b", self.area.id, "Vault B")

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_container_template_reuse_creates_independent_instances(self) -> None:
        template = self.world.create_container_template(
            "test_chest",
            "Test Chest",
            "wooden_chest",
            "Reusable chest.",
        )

        first = self.world.place_container(self.room_a.id, template.template_id)
        second = self.world.place_container(self.room_b.id, template.template_id)
        self.world.update_container(
            first.id,
            name="Locked Test Chest",
            description=first.description,
            has_lock=True,
            is_locked=True,
            is_broken=False,
            unlock_difficulty=17,
            hidden=True,
            discovery_difficulty=14,
            is_open=False,
            searched=False,
        )

        first_after = self.world.get_container(first.id)
        second_after = self.world.get_container(second.id)
        self.assertEqual(first_after.template_id, second_after.template_id)
        self.assertEqual(first_after.room_id, self.room_a.id)
        self.assertEqual(second_after.room_id, self.room_b.id)
        self.assertTrue(first_after.is_locked)
        self.assertTrue(first_after.hidden)
        self.assertEqual(first_after.discovery_difficulty, 14)
        self.assertFalse(second_after.has_lock)
        self.assertFalse(second_after.hidden)
        self.assertEqual(second_after.name, "Test Chest")

    def test_container_contents_reuse_item_library_and_quantities(self) -> None:
        chest = self.world.place_container(self.room_a.id, "wooden_chest")
        holder = InventoryHolder.entity(chest.id)

        placed = self.world.place_catalog_item(holder, "lockpicks", 2)
        changed = self.world.set_item_quantity(holder, "lockpicks", 4)

        self.assertEqual(placed.quantity, 2)
        self.assertEqual(changed.quantity, 4)
        self.assertEqual(
            [(stack.item.id, stack.quantity) for stack in self.world.inventory(holder)],
            [("lockpicks", 4)],
        )

    def test_hidden_container_knowledge_is_per_character(self) -> None:
        hidden = self.world.place_container(self.room_a.id, "loose_floorboard")
        first_character = self.database.create_character(101, "Ada", 10)
        second_character = self.database.create_character(202, "Bryn", 10)
        assert first_character.character_id is not None
        assert second_character.character_id is not None

        self.assertTrue(hidden.hidden)
        self.assertEqual(hidden.discovery_difficulty, 14)
        self.assertFalse(
            self.world.character_knows_container(first_character.character_id, hidden.id)
        )
        self.assertFalse(
            self.world.character_knows_container(second_character.character_id, hidden.id)
        )
        self.world.place_character(first_character.character_id, self.room_a.id)
        self.world.place_character(second_character.character_id, self.room_a.id)
        self.assertNotIn(
            hidden.id,
            {item.id for item in self.world.get_character_room(first_character.character_id).containers},
        )
        self.assertNotIn(
            hidden.id,
            {item.id for item in self.world.get_character_room(second_character.character_id).containers},
        )

        self.world.mark_container_discovered(first_character.character_id, hidden.id)

        self.assertTrue(
            self.world.character_knows_container(first_character.character_id, hidden.id)
        )
        self.assertFalse(
            self.world.character_knows_container(second_character.character_id, hidden.id)
        )
        self.assertIn(
            hidden.id,
            {item.id for item in self.world.get_character_room(first_character.character_id).containers},
        )
        self.assertNotIn(
            hidden.id,
            {item.id for item in self.world.get_character_room(second_character.character_id).containers},
        )

    def test_container_uses_same_lock_validation_as_doors(self) -> None:
        chest = self.world.place_container(
            self.room_a.id,
            "reinforced_chest",
        )
        self.assertTrue(chest.has_lock)
        self.assertTrue(chest.is_locked)
        self.assertEqual(chest.unlock_difficulty, 14)

        with self.assertRaisesRegex(ValueError, "without a lock"):
            self.world.update_container(
                chest.id,
                name=chest.name,
                description=chest.description,
                has_lock=False,
                is_locked=True,
                is_broken=False,
                unlock_difficulty=14,
                hidden=False,
                discovery_difficulty=None,
                is_open=False,
                searched=False,
            )

        self.world.connect_rooms(
            self.room_a.id,
            "east",
            self.room_b.id,
            return_exit_name="west",
            connection_type=ConnectionType.DOOR,
        )
        self.world.set_connection_lock(
            self.room_a.id,
            "east",
            has_lock=True,
            is_locked=True,
            unlock_difficulty=19,
        )
        connection = next(
            item
            for item in self.world.area_graph(self.area.id).connections
            if item.exit_name == "east"
        )
        self.assertTrue(connection.is_locked)
        self.assertEqual(connection.unlock_difficulty, 19)

    def test_editing_and_removing_instance_does_not_change_template_or_sibling(self) -> None:
        first = self.world.place_container(self.room_a.id, "wooden_chest")
        second = self.world.place_container(self.room_a.id, "wooden_chest")

        self.world.update_container(
            first.id,
            name="Mimic-looking Chest",
            description="Only this instance changed.",
            has_lock=True,
            is_locked=False,
            is_broken=True,
            unlock_difficulty=None,
            hidden=False,
            discovery_difficulty=None,
            is_open=False,
            searched=True,
        )
        self.world.remove_container(first.id)

        sibling = self.world.get_container(second.id)
        template = self.world.get_container_template("wooden_chest")
        self.assertIsNone(self.world.get_container(first.id))
        self.assertIsNotNone(sibling)
        self.assertEqual(sibling.name, "Wooden Chest")
        self.assertFalse(sibling.has_lock)
        self.assertEqual(template.name, "Wooden Chest")

    def test_legacy_world_container_remains_readable_as_other(self) -> None:
        legacy = self.world.create_entity(
            "old_box",
            self.room_a.id,
            EntityKind.CONTAINER,
            "Old Box",
        )

        loaded = self.world.get_container(legacy.id)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.template_id, "other")
        self.assertEqual(loaded.container_type, ContainerType.OTHER)

    def test_corpse_uses_the_same_container_inventory_model(self) -> None:
        corpse = self.world.place_container(self.room_a.id, "corpse")
        self.world.place_catalog_item(
            InventoryHolder.entity(corpse.id),
            "lockpicks",
            1,
        )

        self.assertEqual(corpse.container_type, ContainerType.CORPSE)
        self.assertEqual(
            self.world.inventory(InventoryHolder.entity(corpse.id))[0].item.id,
            "lockpicks",
        )


    def test_dashboard_container_flow_places_edits_and_lists_contents(self) -> None:
        from rpg_bot.dashboard.api import DashboardAPI

        api = DashboardAPI(self.world)
        status, created = api.handle(
            "POST",
            f"/api/rooms/{self.room_a.id}/containers",
            {"template_id": "wooden_chest"},
        )
        self.assertEqual(status, 201)
        container_id = created["id"]

        status, _ = api.handle(
            "POST",
            f"/api/containers/{container_id}/items",
            {"item_id": "lockpicks", "quantity": 2},
        )
        self.assertEqual(status, 201)
        status, changed = api.handle(
            "PUT",
            f"/api/containers/{container_id}/items/lockpicks",
            {"quantity": 3},
        )
        self.assertEqual((status, changed["quantity"]), (200, 3))

        status, updated = api.handle(
            "PATCH",
            f"/api/containers/{container_id}",
            {
                "name": "Secret Chest",
                "has_lock": True,
                "is_locked": True,
                "unlock_difficulty": 16,
                "hidden": True,
                "discovery_difficulty": 14,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(updated["is_locked"])
        self.assertTrue(updated["hidden"])
        self.assertEqual(updated["item_count"], 3)

        status, graph = api.handle("GET", f"/api/areas/{self.area.id}/graph")
        self.assertEqual(status, 200)
        room = next(node for node in graph["nodes"] if node["id"] == self.room_a.id)
        summary = next(item for item in room["containers"] if item["id"] == container_id)
        self.assertEqual(summary["name"], "Secret Chest")
        self.assertEqual(summary["item_count"], 3)
        self.assertEqual(summary["discovery_difficulty"], 14)


if __name__ == "__main__":
    unittest.main()
