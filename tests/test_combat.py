import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rpg_bot.combat import (
    CombatantKind,
    LandmarkDistance,
    LandmarkRelation,
)
from rpg_bot.combat_service import CombatError, CombatService
from rpg_bot.database import Database
from rpg_bot.dungeon import ConnectionType
from rpg_bot.world import EntityKind
from rpg_bot.world_service import WorldService


class CombatServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "combat.db"
        self.database = Database(self.database_path)
        self.database.initialize()
        self.world = WorldService(self.database)
        self.area = self.world.create_area("keep", "Old Keep")
        self.hall = self.world.create_room(
            "great_hall",
            self.area.id,
            "Great Hall",
            "A long hall scarred by old fighting.",
        )
        self.other = self.world.create_room(
            "side_room",
            self.area.id,
            "Side Room",
        )
        self.world.create_room_feature(
            self.hall.id,
            "stone_pillar",
            "Stone Pillar",
            "structure",
            "A thick pillar capable of breaking line of sight.",
        )
        self.world.create_room_feature(
            self.hall.id,
            "oak_table",
            "Oak Table",
            "furniture",
            "A broad table with a heavy top.",
        )
        self.olof = self.database.create_character(7, "Olof", 15)
        self.sven = self.database.create_character(8, "Sven", 12)
        assert self.olof.character_id is not None
        assert self.sven.character_id is not None
        self.world.place_character(self.olof.character_id, self.hall.id)
        self.world.place_character(self.sven.character_id, self.other.id)
        self.world.create_entity(
            "bandit",
            self.hall.id,
            EntityKind.ENEMY,
            "Bandit",
        )
        self.service = CombatService(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_start_snapshots_room_features_and_present_combatants(self) -> None:
        scene = self.service.start(44, self.hall.id)

        self.assertEqual(scene.room_id, self.hall.id)
        self.assertEqual(
            {landmark.id for landmark in scene.landmarks},
            {"room:center", "feature:stone_pillar", "feature:oak_table"},
        )
        center = scene.landmark("room:center")
        assert center is not None
        self.assertTrue(center.synthetic)
        self.assertEqual((center.x, center.y), (0.5, 0.5))
        self.assertEqual(
            {(combatant.kind, combatant.name) for combatant in scene.combatants},
            {
                (CombatantKind.CHARACTER, "Olof"),
                (CombatantKind.ENEMY, "Bandit"),
            },
        )
        self.assertNotIn("Sven", {item.name for item in scene.combatants})

    def test_room_doors_become_linked_combat_landmarks(self) -> None:
        connection = self.world.connect_rooms(
            self.hall.id,
            "east gate",
            self.other.id,
            return_exit_name="west gate",
            connection_type=ConnectionType.DOOR,
        )

        scene = self.service.start(44, self.hall.id)
        door = next(
            landmark
            for landmark in scene.landmarks
            if landmark.feature_type == "door"
        )

        self.assertEqual(door.id, f"door:{connection.id}")
        self.assertEqual(door.name, "Door: east gate")
        self.assertEqual(door.source_connection_id, connection.id)
        self.assertIn("Side Room", door.description or "")
        self.assertEqual((door.x, door.y), (0.82, 0.5))
        for feature in (
            landmark
            for landmark in scene.landmarks
            if landmark.source_feature_id is not None
        ):
            assert feature.x is not None
            assert feature.y is not None
            self.assertFalse(
                abs(feature.x - door.x) < 0.20
                and abs(feature.y - door.y) < 0.14
            )
        self.assertEqual(len(scene.routes), 1)
        self.assertEqual(
            {
                scene.routes[0].source_landmark_id,
                scene.routes[0].destination_landmark_id,
            },
            {"room:center", door.id},
        )
        self.assertEqual(scene.routes[0].distance, LandmarkDistance.CLOSE)

        self.service.end(44)
        reverse_scene = self.service.start(44, self.other.id)
        reverse_door = next(
            landmark
            for landmark in reverse_scene.landmarks
            if landmark.feature_type == "door"
        )
        self.assertEqual(reverse_door.name, "Door: west gate")
        self.assertEqual(reverse_door.source_connection_id, connection.id)
        self.assertEqual((reverse_door.x, reverse_door.y), (0.08, 0.5))
        self.assertEqual(len(reverse_scene.routes), 1)

    def test_cardinal_doors_start_on_matching_edges(self) -> None:
        exits = {
            "north": ("north_room", (0.5, 0.08)),
            "east": ("east_room", (0.82, 0.5)),
            "south": ("south_room", (0.5, 0.82)),
            "west": ("west_room", (0.08, 0.5)),
        }
        for exit_name, (room_id, _) in exits.items():
            room = self.world.create_room(
                room_id,
                self.area.id,
                room_id.replace("_", " ").title(),
            )
            self.world.connect_rooms(
                self.hall.id,
                f"{exit_name} door",
                room.id,
                connection_type=ConnectionType.DOOR,
            )

        scene = self.service.start(44, self.hall.id)
        doors = {
            landmark.name.removeprefix("Door: ").split()[0]: landmark
            for landmark in scene.landmarks
            if landmark.feature_type == "door"
        }

        self.assertEqual(len(doors), 4)
        self.assertEqual(len(scene.routes), 4)
        for exit_name, (_, expected_position) in exits.items():
            door = doors[exit_name]
            self.assertEqual((door.x, door.y), expected_position)
            self.assertTrue(
                any(
                    {
                        route.source_landmark_id,
                        route.destination_landmark_id,
                    }
                    == {"room:center", door.id}
                    for route in scene.routes
                )
            )

    def test_same_side_doors_are_offset_instead_of_overlapping(self) -> None:
        for suffix in ("a", "b"):
            room = self.world.create_room(
                f"east_{suffix}",
                self.area.id,
                f"East {suffix.upper()}",
            )
            self.world.connect_rooms(
                self.hall.id,
                f"east door {suffix}",
                room.id,
                connection_type=ConnectionType.DOOR,
            )

        scene = self.service.start(44, self.hall.id)
        east_doors = [
            landmark
            for landmark in scene.landmarks
            if landmark.feature_type == "door"
        ]

        self.assertEqual(len(east_doors), 2)
        self.assertEqual({door.x for door in east_doors}, {0.82})
        self.assertEqual(
            sorted(door.y for door in east_doors if door.y is not None),
            [0.44, 0.56],
        )

    def test_custom_landmark_and_connection_can_be_removed(self) -> None:
        scene = self.service.start(44, self.hall.id)
        scene = self.service.add_landmark(
            44,
            "Broken balcony",
            "A raised ledge overlooking the room.",
        )
        custom = next(
            landmark
            for landmark in scene.landmarks
            if landmark.feature_type == "custom"
        )
        self.assertEqual(custom.name, "Broken balcony")
        self.assertIsNotNone(custom.x)
        self.assertIsNotNone(custom.y)

        scene = self.service.connect_landmarks(
            44,
            "room:center",
            custom.id,
            LandmarkDistance.CLOSE,
        )
        self.assertEqual(len(scene.routes), 1)

        scene = self.service.disconnect_landmarks(
            44,
            "room:center",
            custom.id,
        )
        self.assertEqual(scene.routes, ())

        scene = self.service.remove_landmark(44, custom.id)
        self.assertIsNone(scene.landmark(custom.id))

    def test_source_landmark_cannot_be_removed_from_combat_scene(self) -> None:
        self.service.start(44, self.hall.id)

        with self.assertRaises(CombatError):
            self.service.remove_landmark(44, "feature:stone_pillar")

    def test_feature_snapshot_does_not_change_mid_combat(self) -> None:
        self.service.start(44, self.hall.id)

        self.world.update_room_feature(
            "stone_pillar",
            name="Cracked Pillar",
            description="Fresh cracks split the stone.",
            feature_type="structure",
        )

        scene = self.service.current(44)
        assert scene is not None
        landmark = scene.landmark("feature:stone_pillar")
        assert landmark is not None
        self.assertEqual(landmark.name, "Stone Pillar")
        self.assertEqual(
            landmark.description,
            "A thick pillar capable of breaking line of sight.",
        )

    def test_routes_positions_and_combatant_location_survive_restart(self) -> None:
        scene = self.service.start(44, self.hall.id)
        self.service.set_landmark_position(
            44,
            "feature:stone_pillar",
            0.25,
            0.35,
        )
        self.service.connect_landmarks(
            44,
            "room:center",
            "feature:stone_pillar",
            LandmarkDistance.CLOSE,
            obstacle="Fallen rubble",
        )
        self.service.move_combatant(
            44,
            CombatantKind.CHARACTER,
            str(self.olof.character_id),
            "feature:stone_pillar",
            LandmarkRelation.BEHIND,
        )

        reopened_database = Database(self.database_path)
        reopened_database.initialize()
        reopened = CombatService(reopened_database).current(44)
        assert reopened is not None

        pillar = reopened.landmark("feature:stone_pillar")
        assert pillar is not None
        self.assertEqual((pillar.x, pillar.y), (0.25, 0.35))
        self.assertEqual(len(reopened.routes), 1)
        self.assertEqual(reopened.routes[0].distance, LandmarkDistance.CLOSE)
        self.assertEqual(reopened.routes[0].obstacle, "Fallen rubble")
        olof = next(
            item
            for item in reopened.combatants
            if item.kind is CombatantKind.CHARACTER
        )
        self.assertEqual(olof.landmark_id, "feature:stone_pillar")
        self.assertEqual(olof.relation, LandmarkRelation.BEHIND)
        self.assertEqual(scene.id, reopened.id)

    def test_initiative_uses_insight_and_tracks_dynamic_turn_order(self) -> None:
        with patch(
            "rpg_bot.combat_service.random.randint",
            side_effect=[15, 9, 20],
        ):
            scene = self.service.start(44, self.hall.id)

            self.assertEqual(scene.round_number, 1)
            self.assertEqual(scene.current_turn_kind, CombatantKind.CHARACTER)
            self.assertEqual(
                scene.current_turn_source_id,
                str(self.olof.character_id),
            )
            self.assertEqual(
                [
                    (item.name, item.initiative_score)
                    for item in scene.initiative_order()
                ],
                [("Olof", 15), ("Bandit", 9)],
            )

            scene = self.service.add_enemies(
                44,
                "core_goblin_raider",
            )

        goblin = next(
            item
            for item in scene.combatants
            if item.name == "Goblin Raider"
        )
        self.assertEqual(goblin.initiative_roll, 20)
        self.assertEqual(goblin.initiative_score, 21)
        self.assertEqual(
            scene.current_turn_source_id,
            str(self.olof.character_id),
        )

        scene = self.service.next_turn(44)
        self.assertEqual(scene.current_turn_source_id, "bandit")
        self.assertEqual(scene.round_number, 1)

        scene = self.service.next_turn(44)
        self.assertEqual(scene.current_turn_source_id, goblin.source_id)
        self.assertEqual(scene.round_number, 2)

        scene = self.service.previous_turn(44)
        self.assertEqual(scene.current_turn_source_id, "bandit")
        self.assertEqual(scene.round_number, 1)

        scene = self.service.jump_turn(
            44,
            CombatantKind.CHARACTER,
            str(self.olof.character_id),
        )
        self.assertEqual(
            scene.current_turn_source_id,
            str(self.olof.character_id),
        )

        scene = self.service.set_initiative(
            44,
            CombatantKind.ENEMY,
            "bandit",
            30,
        )
        self.assertEqual(
            scene.current_turn_source_id,
            str(self.olof.character_id),
        )
        self.assertEqual(scene.initiative_order()[0].source_id, "bandit")

        reopened_database = Database(self.database_path)
        reopened_database.initialize()
        reopened = CombatService(reopened_database).current(44)
        assert reopened is not None
        self.assertEqual(reopened.round_number, 1)
        self.assertEqual(
            reopened.current_turn_source_id,
            str(self.olof.character_id),
        )
        self.assertEqual(reopened.initiative_order()[0].initiative_score, 30)

    def test_only_one_active_scene_is_allowed_per_guild(self) -> None:
        self.service.start(44, self.hall.id)

        with self.assertRaisesRegex(CombatError, "already has an active combat"):
            self.service.start(44, self.other.id)

    def test_end_releases_server_for_a_later_scene(self) -> None:
        first = self.service.start(44, self.hall.id)

        ended = self.service.end(44)
        second = self.service.start(44, self.other.id)

        self.assertEqual(ended.id, first.id)
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.room_id, self.other.id)


if __name__ == "__main__":
    unittest.main()
