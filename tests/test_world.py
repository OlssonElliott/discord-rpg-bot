import tempfile
import unittest
from pathlib import Path

from rpg_bot.database import Database
from rpg_bot.world import (
    EntityKind,
    InvalidMovementError,
    InvalidTransferError,
    InventoryHolder,
)
from rpg_bot.world_service import WorldService


class WorldServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "world.db"
        self.database = Database(self.database_path)
        self.database.initialize()
        self.world = WorldService(self.database)
        self.area = self.world.create_area("chapel", "Ruined Chapel", "Old stone.")
        self.entrance = self.world.create_room(
            "chapel_entrance", self.area.id, "Entrance"
        )
        self.hall = self.world.create_room(
            "chapel_hall", self.area.id, "Main Hall", "Dust hangs in the air."
        )
        self.crypt = self.world.create_room("chapel_crypt", self.area.id, "Crypt")
        self.world.connect_rooms(
            self.entrance.id,
            "north",
            self.hall.id,
            return_exit_name="south",
        )
        self.character = self.database.create_character(123, "Olof", 20)
        assert self.character.character_id is not None
        self.character_id = self.character.character_id

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_creates_area_connected_rooms_and_persists_them(self) -> None:
        reopened = WorldService(Database(self.database_path))
        area = reopened.database.get_area("chapel")
        hall = reopened.get_room("chapel_hall")

        self.assertEqual(area.name, "Ruined Chapel")
        self.assertEqual(
            area.room_ids,
            ("chapel_crypt", "chapel_entrance", "chapel_hall"),
        )
        self.assertEqual(
            [(exit.name, exit.destination_room_id) for exit in hall.exits],
            [("south", "chapel_entrance")],
        )

    def test_places_character_and_moves_between_connected_rooms(self) -> None:
        placed = self.world.place_character(self.character_id, self.entrance.id)
        moved = self.world.move_character(self.character_id, "north")

        self.assertEqual(placed.characters[0].name, "Olof")
        self.assertEqual(moved.id, self.hall.id)
        self.assertEqual(
            self.database.get_character(123).current_room_id, self.hall.id
        )
        self.assertEqual(self.world.get_room(self.entrance.id).characters, ())
        self.assertEqual(self.world.get_room(self.hall.id).characters[0].name, "Olof")

    def test_rejects_movement_to_unconnected_room_without_mutation(self) -> None:
        self.world.place_character(self.character_id, self.entrance.id)

        with self.assertRaises(InvalidMovementError):
            self.world.move_character(self.character_id, self.crypt.id)

        self.assertEqual(
            self.world.get_character_room(self.character_id).id, self.entrance.id
        )

    def test_takes_and_drops_loose_stacked_items_without_duplication(self) -> None:
        self.world.place_character(self.character_id, self.entrance.id)
        self.world.create_item("health_potion", "Health Potion")
        room_holder = InventoryHolder.room(self.entrance.id)
        self.world.place_item(room_holder, "health_potion", 3)

        moved = self.world.take_loose_item(self.character_id, "health_potion", 2)

        self.assertEqual((moved.item.name, moved.quantity), ("Health Potion", 2))
        self.assertEqual(self.world.inventory(room_holder)[0].quantity, 1)
        rich_inventory = self.database.get_character_inventory(self.character_id)
        potion = next(
            item for item in rich_inventory.items if item.template_id == "health_potion"
        )
        self.assertEqual(potion.quantity, 2)

        self.world.drop_item(self.character_id, "Health Potion", 1)

        self.assertEqual(self.world.inventory(room_holder)[0].quantity, 2)
        rich_inventory = self.database.get_character_inventory(self.character_id)
        potion = next(
            item for item in rich_inventory.items if item.template_id == "health_potion"
        )
        self.assertEqual(potion.quantity, 1)
        self.assertEqual(
            sum(stack.quantity for stack in self.world.inventory(room_holder))
            + sum(
                item.quantity
                for item in rich_inventory.items
                if item.template_id != "common_clothing"
            ),
            3,
        )

    def test_item_disappears_from_room_after_full_transfer(self) -> None:
        self.world.place_character(self.character_id, self.entrance.id)
        self.world.create_item("rusty_sword", "Rusty Sword", stackable=False)
        self.world.place_item(InventoryHolder.room(self.entrance.id), "rusty_sword")

        self.world.take_loose_item(self.character_id, "Rusty Sword")

        self.assertEqual(self.world.get_room(self.entrance.id).loose_items, ())
        inventory = self.database.get_character_inventory(self.character_id)
        self.assertEqual(
            [
                (item.template_id, item.quantity)
                for item in inventory.items
                if item.template_id != "common_clothing"
            ],
            [("rusty_sword", 1)],
        )

    def test_uncatalogued_item_cannot_enter_character_inventory(self) -> None:
        self.world.place_character(self.character_id, self.entrance.id)
        self.world.create_item("old_key", "Unregistered Key", stackable=False)
        room_holder = InventoryHolder.room(self.entrance.id)
        self.world.place_item(room_holder, "old_key")

        with self.assertRaisesRegex(InvalidTransferError, "shared item library"):
            self.world.take_loose_item(self.character_id, "old_key")

        self.assertEqual(self.world.inventory(room_holder)[0].item.id, "old_key")
        self.assertEqual(
            [
                item.template_id
                for item in self.database.get_character_inventory(
                    self.character_id
                ).items
            ],
            ["common_clothing"],
        )

    def test_catalog_loot_uses_the_interactive_character_inventory(self) -> None:
        self.world.place_character(self.character_id, self.entrance.id)
        self.world.create_item("found_potion", "Health Potion")
        self.world.place_item(
            InventoryHolder.room(self.entrance.id), "found_potion", 2
        )

        self.world.take_loose_item(self.character_id, "Health Potion", 2)

        self.assertEqual(self.world.get_room(self.entrance.id).loose_items, ())
        inventory = self.database.get_character_inventory(self.character_id)
        self.assertEqual(
            [
                (item.template_id, item.quantity)
                for item in inventory.items
                if item.template_id != "common_clothing"
            ],
            [("health_potion", 2)],
        )

        self.world.drop_item(self.character_id, "Health Potion")

        inventory = self.database.get_character_inventory(self.character_id)
        potion = next(
            item for item in inventory.items if item.template_id == "health_potion"
        )
        self.assertEqual(potion.quantity, 1)
        self.assertEqual(
            [(stack.item.id, stack.quantity) for stack in self.world.get_room(self.entrance.id).loose_items],
            [("health_potion", 1)],
        )

    def test_transfers_items_from_container(self) -> None:
        chest = self.world.create_entity(
            "wooden_chest", self.hall.id, EntityKind.CONTAINER, "Wooden Chest"
        )
        self.world.create_item("health_potion", "Health Potion")
        chest_holder = InventoryHolder.entity(chest.id)
        self.world.place_character(self.character_id, self.hall.id)
        self.world.place_item(chest_holder, "health_potion", 2)

        self.world.take_from_container(self.character_id, chest.id, "Health Potion")

        self.assertEqual(self.world.inventory(chest_holder)[0].quantity, 1)
        inventory = self.database.get_character_inventory(self.character_id)
        potion = next(
            item for item in inventory.items if item.template_id == "health_potion"
        )
        self.assertEqual(potion.quantity, 1)
        self.assertEqual(self.world.get_room(self.hall.id).containers, (chest,))

    def test_player_can_only_take_from_a_container_in_their_room(self) -> None:
        chest = self.world.create_entity(
            "remote_chest", self.hall.id, EntityKind.CONTAINER, "Remote Chest"
        )
        self.world.create_item("iron_dagger", "Iron Dagger", stackable=False)
        self.world.place_item(InventoryHolder.entity(chest.id), "iron_dagger")
        self.world.place_character(self.character_id, self.entrance.id)

        with self.assertRaises(InvalidTransferError):
            self.world.take_from_container(self.character_id, chest.id, "iron_dagger")

        self.world.move_character(self.character_id, "north")
        self.world.take_from_container(self.character_id, chest.id, "iron_dagger")
        self.assertEqual(self.world.inventory(InventoryHolder.entity(chest.id)), ())
        inventory = self.database.get_character_inventory(self.character_id)
        self.assertTrue(
            any(item.template_id == "iron_dagger" for item in inventory.items)
        )

    def test_location_and_room_contents_survive_restart(self) -> None:
        self.world.place_character(self.character_id, self.entrance.id)
        self.world.create_item("lantern", "Broken Lantern")
        self.world.place_item(InventoryHolder.room(self.entrance.id), "lantern")

        reopened_database = Database(self.database_path)
        reopened_database.initialize()
        room = WorldService(reopened_database).get_character_room(self.character_id)

        self.assertEqual(room.id, self.entrance.id)
        self.assertEqual(room.characters[0].name, "Olof")
        self.assertEqual(room.loose_items[0].item.name, "Broken Lantern")

    def test_rejects_missing_or_excess_transfer_atomically(self) -> None:
        self.world.create_item("coin", "Coin")
        source = InventoryHolder.room(self.entrance.id)
        destination = InventoryHolder.character(self.character_id)
        self.world.place_item(source, "coin", 2)

        with self.assertRaises(InvalidTransferError):
            self.world.transfer_item(source, destination, "missing")
        with self.assertRaises(InvalidTransferError):
            self.world.transfer_item(source, destination, "coin", 3)

        self.assertEqual(self.world.inventory(source)[0].quantity, 2)
        self.assertEqual(self.world.inventory(destination), ())

    def test_room_answers_entity_category_questions(self) -> None:
        enemy = self.world.create_entity(
            "bandit", self.hall.id, EntityKind.ENEMY, "Bandit"
        )
        npc = self.world.create_entity("priest", self.hall.id, EntityKind.NPC, "Priest")
        container = self.world.create_entity(
            "cabinet", self.hall.id, EntityKind.CONTAINER, "Cabinet"
        )

        room = self.world.get_room(self.hall.id)

        self.assertEqual(room.enemies, (enemy,))
        self.assertEqual(room.npcs, (npc,))
        self.assertEqual(room.containers, (container,))

    def test_editor_position_persists_without_changing_gameplay_location(self) -> None:
        self.world.place_character(self.character_id, self.entrance.id)
        self.world.set_room_editor_position(self.hall.id, 420.5, -260)

        graph = WorldService(Database(self.database_path)).area_graph(self.area.id)
        hall_node = next(node for node in graph.nodes if node.room.id == self.hall.id)

        self.assertEqual((hall_node.x, hall_node.y), (420.5, -260.0))
        self.assertEqual(
            self.world.get_character_room(self.character_id).id, self.entrance.id
        )

    def test_rejects_malformed_editor_coordinates(self) -> None:
        for x, y in ((float("nan"), 2), (1, float("inf")), (1_000_001, 0)):
            with self.subTest(x=x, y=y):
                with self.assertRaises(ValueError):
                    self.world.set_room_editor_position(self.hall.id, x, y)

    def test_rejects_connection_to_room_in_another_area(self) -> None:
        other_area = self.world.create_area("forest", "Old Forest")
        clearing = self.world.create_room("clearing", other_area.id, "Clearing")

        with self.assertRaises(InvalidMovementError):
            self.world.connect_rooms(self.hall.id, "outside", clearing.id)

    def test_disconnects_rooms(self) -> None:
        self.world.disconnect_rooms(self.entrance.id, "north")

        graph = self.world.area_graph(self.area.id)

        self.assertNotIn(
            (self.entrance.id, "north", self.hall.id),
            [
                (
                    connection.source_room_id,
                    connection.exit_name,
                    connection.destination_room_id,
                )
                for connection in graph.connections
            ],
        )
        self.assertNotIn(
            (self.hall.id, "south", self.entrance.id),
            [
                (
                    connection.source_room_id,
                    connection.exit_name,
                    connection.destination_room_id,
                )
                for connection in graph.connections
            ],
        )

    def test_changes_connection_between_one_way_and_two_way(self) -> None:
        self.world.set_connection_direction(
            self.entrance.id, "north", bidirectional=False
        )

        self.assertEqual(self.world.get_room(self.hall.id).exits, ())
        connection = self.world.area_graph(self.area.id).connections[0]
        self.assertFalse(connection.bidirectional)
        self.assertIsNone(connection.return_exit_name)

        self.world.set_connection_direction(
            self.entrance.id,
            "north",
            bidirectional=True,
            return_exit_name="back",
        )

        self.assertEqual(
            [(exit.name, exit.destination_room_id) for exit in self.world.get_room(self.hall.id).exits],
            [("back", self.entrance.id)],
        )
        connection = self.world.area_graph(self.area.id).connections[0]
        self.assertTrue(connection.bidirectional)
        self.assertEqual(connection.return_exit_name, "back")

    def test_deleting_empty_room_removes_all_attached_edges(self) -> None:
        self.world.connect_rooms(self.hall.id, "down", self.crypt.id)

        self.world.delete_room(self.hall.id)

        graph = self.world.area_graph(self.area.id)
        self.assertNotIn(self.hall.id, [node.room.id for node in graph.nodes])
        self.assertFalse(
            any(
                self.hall.id
                in (connection.source_room_id, connection.destination_room_id)
                for connection in graph.connections
            )
        )

    def test_deleting_occupied_room_is_rejected(self) -> None:
        self.world.place_character(self.character_id, self.hall.id)

        with self.assertRaises(ValueError):
            self.world.delete_room(self.hall.id)

        self.assertIsNotNone(self.world.get_room(self.hall.id))


if __name__ == "__main__":
    unittest.main()
