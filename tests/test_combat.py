import tempfile
import unittest
from pathlib import Path

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

        self.service.end(44)
        reverse_scene = self.service.start(44, self.other.id)
        reverse_door = next(
            landmark
            for landmark in reverse_scene.landmarks
            if landmark.feature_type == "door"
        )
        self.assertEqual(reverse_door.name, "Door: west gate")
        self.assertEqual(reverse_door.source_connection_id, connection.id)

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
