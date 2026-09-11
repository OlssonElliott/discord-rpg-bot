import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import Mock

from PIL import Image

from rpg_bot.database import Database
from rpg_bot.discord_player_view import DiscordPlayerViewAdapter
from rpg_bot.dungeon import ConnectionType, GameLock, KnowledgeSource, KnowledgeState
from rpg_bot.player_view_service import PlayerViewMessageService, PlayerViewService
from rpg_bot.map_renderer import (
    MAP_HEIGHT,
    MAP_WIDTH,
    MIN_ROOM_HEIGHT,
    MIN_ROOM_WIDTH,
    _layout,
    render_player_map,
)
from rpg_bot.world import InvalidMovementError
from rpg_bot.world_service import WorldService


class PlayerViewServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "views.db")
        self.database.initialize()
        self.world = WorldService(self.database)
        self.views = PlayerViewService(self.database)
        self.dungeon = self.world.create_area("abbey", "Sunken Abbey")
        self.lower = self.world.create_floor("abbey:lower", "abbey", -1, "Lower Crypt")
        self.entrance = self.world.create_room(
            "entrance",
            "abbey",
            "Entrance",
            "Rain runs down the old doors.",
            editor_x=10,
            editor_y=20,
            width=3,
            height=2,
            scene_image_path="scenes/entrance.png",
        )
        self.chapel = self.world.create_room(
            "chapel",
            "abbey",
            "Chapel",
            "Broken pews face a dark altar.",
            editor_x=50,
            editor_y=20,
            scene_image_url="https://assets.example/chapel.png",
        )
        self.unknown = self.world.create_room("sealed", "abbey", "Sealed Vault")
        self.cellar = self.world.create_room(
            "cellar", "abbey", "Cellar", floor_id=self.lower.id
        )
        self.door = self.world.connect_rooms(
            "entrance", "east", "chapel", return_exit_name="west",
            connection_type=ConnectionType.DOOR,
        )
        self.stairs = self.world.connect_rooms(
            "chapel", "down", "cellar", return_exit_name="up",
            connection_type=ConnectionType.STAIRS_DOWN,
        )
        self.alice = self.database.create_character(1, "Alice", 10)
        self.bob = self.database.create_character(2, "Bob", 10)
        assert self.alice.character_id is not None
        assert self.bob.character_id is not None
        self.alice_id = self.alice.character_id
        self.bob_id = self.bob.character_id

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_visiting_room_creates_visited_knowledge_and_reveals_image(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)

        knowledge = self.database.get_character_knowledge(
            self.alice_id, self.entrance.id
        )
        view = self.views.build_player_map(self.alice_id)

        self.assertEqual(knowledge.state, KnowledgeState.VISITED)
        self.assertIsNotNone(knowledge.first_visited_at)
        self.assertEqual(view.focused_room.scene_image_path, "scenes/entrance.png")

    def test_repairs_current_room_when_legacy_character_has_no_knowledge(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        with self.database._connect() as connection:
            connection.execute(
                "DELETE FROM character_room_knowledge WHERE character_id = ?",
                (self.alice_id,),
            )
            connection.execute(
                "DELETE FROM character_known_connections WHERE character_id = ?",
                (self.alice_id,),
            )

        self.database.ensure_character_location_knowledge(self.alice_id)
        view = self.views.build_player_map(self.alice_id)

        current = next(room for room in view.rooms if room.id == self.entrance.id)
        self.assertTrue(current.is_current)
        self.assertEqual(current.knowledge_state, KnowledgeState.VISITED)
        self.assertEqual(view.focused_room.description, self.entrance.description)
        rendered = render_player_map(view)
        self.assertEqual(rendered.read(8), b"\x89PNG\r\n\x1a\n")

    def test_hud_renders_a_large_readable_map(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)

        rendered = render_player_map(self.views.build_player_map(self.alice_id))

        with Image.open(rendered) as image:
            self.assertEqual(image.size, (1600, 1000))

    def test_hud_centers_current_room_when_known_bounds_allow_it(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        view = self.views.build_player_map(self.alice_id)

        positions = _layout(view)
        left, top, width, height = positions[self.entrance.id]

        self.assertAlmostEqual(left + width / 2, MAP_WIDTH / 2)
        self.assertAlmostEqual(top + height / 2, MAP_HEIGHT / 2, delta=60)

    def test_hud_rooms_keep_space_for_multiple_player_markers(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        self.world.place_character(self.bob_id, self.entrance.id)
        view = self.views.build_player_map(self.alice_id)

        current = next(room for room in view.rooms if room.is_current)
        positions = _layout(view)

        self.assertEqual(current.visible_characters, ("Alice", "Bob"))
        self.assertGreaterEqual(positions[current.id][2], MIN_ROOM_WIDTH)
        self.assertGreaterEqual(positions[current.id][3], MIN_ROOM_HEIGHT)
        rendered = render_player_map(view)
        self.assertEqual(rendered.read(8), b"\x89PNG\r\n\x1a\n")

    def test_visited_room_hud_shows_status_description_and_scene(self) -> None:
        self.world.place_character(self.alice_id, self.chapel.id)
        view = self.views.build_player_map(self.alice_id)
        adapter = DiscordPlayerViewAdapter(self.database, self.views, Mock())

        embeds, files, controls = adapter._message_parts(view)
        try:
            self.assertEqual(
                embeds[0].description,
                "**Gold** marks where you stand. **Bone** marks what you inspect.\n"
                "Dashed chambers remain unvisited.",
            )
            detail = embeds[1]
            self.assertEqual(detail.author.name, "CURRENT ROOM")
            self.assertEqual(detail.title, "Chapel")
            self.assertEqual(detail.description, self.chapel.description)
            self.assertEqual(detail.fields[0].name, "Journal")
            self.assertEqual(detail.fields[0].value, "You are here.")
            self.assertEqual(detail.image.url, self.chapel.scene_image_url)
            self.assertEqual(detail.footer.text, "Visual memory")
            room_select = next(
                control
                for control in controls.children
                if getattr(control, "placeholder", None)
                == "Inspect room"
            )
            self.assertIsNotNone(room_select)
            refresh = next(
                control
                for control in controls.children
                if getattr(control, "label", None) == "Consult map"
            )
            self.assertIsNone(refresh.emoji)
        finally:
            for file in files:
                file.close()

    def test_shared_known_room_is_uncertain_and_does_not_reveal_scene(self) -> None:
        self.world.place_character(self.alice_id, self.chapel.id)

        shared = self.views.share_room_knowledge(
            self.alice_id, self.bob_id, self.chapel.id
        )
        self.views.focus_room(self.bob_id, self.chapel.id)
        view = self.views.build_player_map(self.bob_id)

        self.assertEqual(shared.state, KnowledgeState.KNOWN)
        self.assertEqual(shared.source, KnowledgeSource.SHARED)
        self.assertEqual(shared.shared_by_character_id, self.alice_id)
        self.assertEqual(view.rooms[0].knowledge_state, KnowledgeState.KNOWN)
        self.assertEqual(view.rooms[0].display_name, "? Chapel")
        self.assertIsNone(view.focused_room.scene_image_url)
        self.assertIsNone(view.focused_room.description)

    def test_known_room_hud_never_renders_hidden_details(self) -> None:
        self.world.place_character(self.alice_id, self.chapel.id)
        self.views.share_room_knowledge(self.alice_id, self.bob_id, self.chapel.id)
        self.views.focus_room(self.bob_id, self.chapel.id)
        view = self.views.build_player_map(self.bob_id)
        adapter = DiscordPlayerViewAdapter(self.database, self.views, Mock())

        embeds, files, _controls = adapter._message_parts(view)
        try:
            detail = embeds[1]
            self.assertEqual(detail.author.name, "KNOWN · UNVISITED")
            self.assertEqual(detail.title, "? Chapel")
            self.assertIn("not yet present", detail.description)
            self.assertEqual(detail.fields[0].name, "Journal")
            self.assertEqual(detail.fields[0].value, "Not personally visited.")
            self.assertIsNone(detail.image.url)
            self.assertEqual(len(files), 1)
        finally:
            for file in files:
                file.close()

    def test_unknown_rooms_are_absent_and_characters_have_separate_knowledge(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        self.world.place_character(self.bob_id, self.unknown.id)

        alice_ids = {room.id for room in self.views.build_player_map(self.alice_id).rooms}
        bob_ids = {room.id for room in self.views.build_player_map(self.bob_id).rooms}

        self.assertEqual(alice_ids, {"entrance", "chapel"})
        self.assertEqual(bob_ids, {"sealed"})

    def test_focusing_old_room_does_not_move_character(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        self.world.move_character(self.alice_id, "east")

        state = self.views.focus_room(self.alice_id, self.entrance.id)

        self.assertEqual(state.focused_room_id, self.entrance.id)
        self.assertEqual(
            self.world.get_character_room(self.alice_id).id, self.chapel.id
        )

    def test_cross_floor_connection_keeps_both_floor_ids(self) -> None:
        self.world.place_character(self.alice_id, self.chapel.id)

        ground_view = self.views.build_player_map(
            self.alice_id, "abbey:floor:1"
        )
        lower_view = self.views.build_player_map(self.alice_id, self.lower.id)
        ground_stairs = next(
            item for item in ground_view.connections if item.id == self.stairs.id
        )
        lower_stairs = next(
            item for item in lower_view.connections if item.id == self.stairs.id
        )

        self.assertEqual(
            (ground_stairs.from_floor_id, ground_stairs.to_floor_id),
            ("abbey:floor:1", self.lower.id),
        )
        self.assertEqual(lower_stairs, ground_stairs)

        reopened = Database(self.database.path)
        reopened.initialize()
        with reopened._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM room_connections"
            ).fetchone()["count"]
        self.assertEqual(count, 2)

    def test_game_lock_blocks_player_movement_without_changing_location(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        self.world.set_game_lock(GameLock.MOVEMENT_LOCKED)

        with self.assertRaisesRegex(InvalidMovementError, "locked"):
            self.world.move_character(self.alice_id, "east")

        self.assertEqual(
            self.world.get_character_room(self.alice_id).id, self.entrance.id
        )

    def test_legacy_area_room_and_exit_gain_floor_and_connection_metadata(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE areas (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT
                );
                CREATE TABLE rooms (
                    id TEXT PRIMARY KEY, area_id TEXT NOT NULL,
                    name TEXT NOT NULL, description TEXT
                );
                CREATE TABLE room_exits (
                    room_id TEXT NOT NULL, name TEXT NOT NULL COLLATE NOCASE,
                    destination_room_id TEXT NOT NULL,
                    PRIMARY KEY (room_id, name)
                );
                INSERT INTO areas VALUES ('old', 'Old Dungeon', NULL);
                INSERT INTO rooms VALUES ('one', 'old', 'One', NULL);
                INSERT INTO rooms VALUES ('two', 'old', 'Two', NULL);
                INSERT INTO room_exits VALUES ('one', 'north', 'two');
                """
            )
            connection.commit()

        migrated = Database(legacy_path)
        migrated.initialize()
        dungeon = migrated.get_dungeon("old")

        self.assertEqual(dungeon.floors[0].id, "old:floor:1")
        self.assertEqual(migrated.get_room("one").floor_id, "old:floor:1")
        with migrated._connect() as raw_connection:
            count = raw_connection.execute(
                "SELECT COUNT(*) AS count FROM room_connections"
            ).fetchone()["count"]
        self.assertEqual(count, 1)


class FakeMessageAdapter:
    def __init__(self) -> None:
        self.message_exists = False
        self.created = 0
        self.edited = 0

    async def edit_view_message(self, channel_id, message_id, view):
        self.edited += 1
        return self.message_exists

    async def create_view_message(self, channel_id, view):
        self.created += 1
        self.message_exists = True
        return 9000 + self.created


class PlayerViewMessageServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_recreates_missing_message_then_edits_persisted_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "message.db")
            database.initialize()
            world = WorldService(database)
            dungeon = world.create_area("keep", "Keep")
            room = world.create_room("gate", dungeon.id, "Gate")
            character = database.create_character(1, "Alice", 10)
            assert character.character_id is not None
            world.place_character(character.character_id, room.id)
            views = PlayerViewService(database)
            views.bind_discord_channel(character.character_id, 77)
            adapter = FakeMessageAdapter()
            messages = PlayerViewMessageService(views, adapter)

            first_id = await messages.refresh(character.character_id)
            second_id = await messages.refresh(character.character_id)
            persisted = database.get_player_view_state(character.character_id)

            self.assertEqual((first_id, second_id), (9001, 9001))
            self.assertEqual((adapter.created, adapter.edited), (1, 1))
            self.assertEqual(persisted.discord_message_id, 9001)


if __name__ == "__main__":
    unittest.main()
