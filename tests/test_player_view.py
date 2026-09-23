import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
import sqlite3
from unittest.mock import Mock

from PIL import Image

from rpg_bot.database import Database
from rpg_bot.player_view.adapter import DiscordPlayerViewAdapter
from rpg_bot.world.dungeon import (
    ConnectionType,
    Floor,
    GameLock,
    KnowledgeSource,
    KnowledgeState,
    PlayerMap,
    PlayerMapConnection,
    PlayerMapRoom,
    TrapDamageType,
    TrapState,
)
from rpg_bot.player_view.service import PlayerViewMessageService, PlayerViewService
from rpg_bot.media.room_images import RoomImageStore
from rpg_bot.map_renderer import (
    CONNECTION_ART_HEIGHT,
    CONNECTION_ROOM_GAP,
    DOOR_ART_PATH,
    OPEN_DOOR_ART_PATH,
    HALLWAY_ART_PATH,
    LOCKED_ART_PATH,
    BROKEN_LOCK_ART_PATH,
    LOCK_ART_HEIGHT,
    MAP_BACKGROUND_PATH,
    MAP_HEIGHT,
    MAP_WIDTH,
    MIN_ROOM_HEIGHT,
    MIN_ROOM_WIDTH,
    ROOM_ART_PATH,
    UNLOCKED_ART_PATH,
    TRAP_ART_HEIGHT,
    TRAP_ART_PATH,
    TRAP_DISARMED_ART_PATH,
    TRAP_TRIGGERED_ART_PATH,
    VIEWPORT_BOUNDS,
    WORLD_TO_MAP_SCALE,
    _draw_connector_art,
    _door_visual_anchor,
    _door_marker_layout,
    _focus_distances,
    _fog_strength,
    _layout,
    _loaded_room_art,
    _loaded_door_art,
    _loaded_open_door_art,
    _loaded_hallway_art,
    _loaded_locked_art,
    _loaded_broken_lock_art,
    _map_canvas,
    _loaded_unlocked_art,
    _loaded_trap_art,
    _loaded_disarmed_trap_art,
    _loaded_triggered_trap_art,
    _trap_marker_position,
    render_player_map,
)
from rpg_bot.world import InvalidMovementError, InventoryHolder
from rpg_bot.world.service import WorldService


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
            is_open=True,
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

    def test_hud_uses_packaged_map_background(self) -> None:
        self.assertTrue(MAP_BACKGROUND_PATH.is_file())
        with Image.open(MAP_BACKGROUND_PATH) as source:
            expected = source.convert("RGB").resize(
                (MAP_WIDTH, MAP_HEIGHT), Image.Resampling.LANCZOS
            )

        canvas = _map_canvas()

        self.assertEqual(canvas.getpixel((800, 500)), expected.getpixel((800, 500)))
        self.assertEqual(canvas.getpixel((20, 20)), expected.getpixel((20, 20)))

    def test_hud_uses_packaged_room_art(self) -> None:
        self.assertTrue(ROOM_ART_PATH.is_file())

        room = _loaded_room_art()

        self.assertIsNotNone(room)
        assert room is not None
        self.assertEqual(room.mode, "RGBA")
        self.assertLess(room.width, 1672)
        self.assertLess(room.height, 941)
        visible_bounds = room.getchannel("A").point(
            lambda value: 255 if value >= 16 else 0
        ).getbbox()
        self.assertEqual(visible_bounds, (0, 0, room.width, room.height))

    def test_hud_uses_equally_sized_upright_connection_art(self) -> None:
        self.assertTrue(DOOR_ART_PATH.is_file())
        self.assertTrue(HALLWAY_ART_PATH.is_file())

        door = _loaded_door_art()
        hallway = _loaded_hallway_art()

        self.assertIsNotNone(door)
        self.assertIsNotNone(hallway)
        assert door is not None
        assert hallway is not None
        for connection_type, artwork in (
            (ConnectionType.DOOR, door),
            (ConnectionType.HALLWAY, hallway),
        ):
            with self.subTest(connection_type=connection_type):
                self.assertEqual(artwork.mode, "RGBA")
                self.assertEqual(artwork.height, CONNECTION_ART_HEIGHT)
                self.assertGreater(artwork.height, artwork.width)
                canvas = Image.new("RGB", (160, 160), "black")
                self.assertTrue(
                    _draw_connector_art(
                        canvas, (80, 80), connection_type, fog_strength=0
                    )
                )
                changed_bounds = canvas.convert("L").point(
                    lambda value: 255 if value else 0
                ).getbbox()
                self.assertIsNotNone(changed_bounds)
                assert changed_bounds is not None
                self.assertGreater(
                    changed_bounds[3] - changed_bounds[1],
                    changed_bounds[2] - changed_bounds[0],
                )

    def test_open_door_uses_distinct_equally_sized_art(self) -> None:
        self.assertTrue(OPEN_DOOR_ART_PATH.is_file())
        closed_art = _loaded_door_art()
        open_art = _loaded_open_door_art()
        self.assertIsNotNone(closed_art)
        self.assertIsNotNone(open_art)
        assert closed_art is not None and open_art is not None
        self.assertEqual(closed_art.height, open_art.height)

        closed = Image.new("RGB", (180, 180), "black")
        opened = Image.new("RGB", (180, 180), "black")
        _draw_connector_art(
            closed, (90, 90), ConnectionType.DOOR, fog_strength=0
        )
        _draw_connector_art(
            opened,
            (90, 90),
            ConnectionType.DOOR,
            is_open=True,
            fog_strength=0,
        )
        self.assertNotEqual(closed.tobytes(), opened.tobytes())

    def test_legacy_passage_uses_hallway_art(self) -> None:
        hallway = _loaded_hallway_art()
        self.assertIsNotNone(hallway)
        canvas = Image.new("RGB", (160, 160), "black")

        self.assertTrue(
            _draw_connector_art(
                canvas, (80, 80), ConnectionType.PASSAGE, fog_strength=0
            )
        )

    def test_door_uses_locked_and_unlocked_overlay_art(self) -> None:
        self.assertTrue(LOCKED_ART_PATH.is_file())
        self.assertTrue(UNLOCKED_ART_PATH.is_file())
        locked_art = _loaded_locked_art()
        unlocked_art = _loaded_unlocked_art()
        self.assertIsNotNone(locked_art)
        self.assertIsNotNone(unlocked_art)
        assert locked_art is not None
        assert unlocked_art is not None
        self.assertEqual(locked_art.height, LOCK_ART_HEIGHT)
        self.assertEqual(unlocked_art.height, LOCK_ART_HEIGHT)

        locked = Image.new("RGB", (160, 160), "black")
        unlocked = Image.new("RGB", (160, 160), "black")
        _draw_connector_art(
            locked,
            (80, 80),
            ConnectionType.DOOR,
            has_lock=True,
            is_locked=True,
            fog_strength=0,
        )
        _draw_connector_art(
            unlocked,
            (80, 80),
            ConnectionType.DOOR,
            has_lock=True,
            is_locked=False,
            fog_strength=0,
        )

        self.assertNotEqual(locked.tobytes(), unlocked.tobytes())

        no_lock = Image.new("RGB", (160, 160), "black")
        _draw_connector_art(
            no_lock,
            (80, 80),
            ConnectionType.DOOR,
            has_lock=False,
            fog_strength=0,
        )
        self.assertNotEqual(no_lock.tobytes(), unlocked.tobytes())

    def test_broken_lock_uses_its_distinct_overlay_art(self) -> None:
        self.assertTrue(BROKEN_LOCK_ART_PATH.is_file())
        broken_art = _loaded_broken_lock_art()
        self.assertIsNotNone(broken_art)
        assert broken_art is not None
        self.assertEqual(broken_art.height, LOCK_ART_HEIGHT)

        broken = Image.new("RGB", (180, 180), "black")
        unlocked = Image.new("RGB", (180, 180), "black")
        _draw_connector_art(
            broken,
            (90, 90),
            ConnectionType.DOOR,
            has_lock=True,
            is_broken=True,
            fog_strength=0,
        )
        _draw_connector_art(
            unlocked,
            (90, 90),
            ConnectionType.DOOR,
            has_lock=True,
            fog_strength=0,
        )
        self.assertNotEqual(broken.tobytes(), unlocked.tobytes())

    def test_vertical_door_stays_full_size_with_lock_to_its_left(self) -> None:
        scale, door_position, lock_position = _door_marker_layout(
            (80, 80),
            (48, 72),
            (28, 28),
            vertical=True,
            door_visual_anchor=(23.5, 38.5),
        )

        self.assertEqual(scale, 1)
        self.assertIsNotNone(lock_position)
        assert lock_position is not None
        self.assertLessEqual(lock_position[0] + 28, door_position[0])
        self.assertAlmostEqual(
            door_position[0] + 23.5,
            80,
            delta=0.5,
        )
        self.assertAlmostEqual(
            door_position[1] + 38.5,
            80,
            delta=0.5,
        )

    def test_trap_art_is_lock_sized_and_placed_opposite_the_lock(self) -> None:
        self.assertTrue(TRAP_ART_PATH.is_file())
        trap = _loaded_trap_art()
        self.assertIsNotNone(trap)
        assert trap is not None
        self.assertEqual(trap.height, TRAP_ART_HEIGHT)

        vertical = _trap_marker_position(
            (80, 80), (56, 44), (48, 72), trap.size, vertical=True
        )
        horizontal = _trap_marker_position(
            (80, 80), (56, 44), (48, 72), trap.size, vertical=False
        )
        self.assertGreaterEqual(vertical[0], 56 + 48)
        self.assertGreaterEqual(horizontal[1], 44 + 72)

    def test_trap_state_selects_distinct_map_art(self) -> None:
        self.assertTrue(TRAP_DISARMED_ART_PATH.is_file())
        self.assertTrue(TRAP_TRIGGERED_ART_PATH.is_file())
        armed = _loaded_trap_art()
        disarmed = _loaded_disarmed_trap_art()
        triggered = _loaded_triggered_trap_art()
        self.assertIsNotNone(armed)
        self.assertIsNotNone(disarmed)
        self.assertIsNotNone(triggered)
        assert armed is not None and disarmed is not None and triggered is not None
        self.assertEqual(armed.height, disarmed.height)
        self.assertEqual(armed.height, triggered.height)
        self.assertNotEqual(armed.tobytes(), disarmed.tobytes())
        self.assertNotEqual(armed.tobytes(), triggered.tobytes())

        renders = []
        for state in TrapState:
            canvas = Image.new("RGB", (220, 180), "black")
            _draw_connector_art(
                canvas,
                (100, 80),
                ConnectionType.DOOR,
                has_trap=True,
                trap_state=state,
                fog_strength=0,
                vertical=True,
            )
            renders.append(canvas.tobytes())
        self.assertEqual(len(set(renders)), 3)

    def test_packaged_door_uses_its_visible_center_as_connector_anchor(self) -> None:
        anchor = _door_visual_anchor()
        self.assertIsNotNone(anchor)
        assert anchor is not None
        door = _loaded_door_art()
        assert door is not None

        _scale, door_position, _lock_position = _door_marker_layout(
            (100, 100),
            door.size,
            (28, 28),
            door_visual_anchor=anchor,
        )

        self.assertAlmostEqual(door_position[0] + anchor[0], 100, delta=0.5)
        self.assertAlmostEqual(door_position[1] + anchor[1], 100, delta=0.5)

    def test_player_map_carries_persisted_door_lock_state(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        self.world.set_connection_lock(
            self.entrance.id,
            "east",
            has_lock=True,
            is_locked=True,
            unlock_difficulty=18,
        )

        view = self.views.build_player_map(self.alice_id)
        door = next(
            connection
            for connection in view.connections
            if connection.id == self.door.id
        )

        self.assertTrue(door.is_locked)
        self.assertTrue(door.has_lock)

    def test_player_map_carries_persisted_trap_marker_state(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        self.world.set_connection_trap(
            self.entrance.id,
            "east",
            has_trap=True,
            trap_state=TrapState.TRIGGERED,
            trap_detection_difficulty=15,
            trap_damage_type=TrapDamageType.POISON,
            trap_damage=6,
        )

        view = self.views.build_player_map(self.alice_id)
        door = next(
            connection
            for connection in view.connections
            if connection.id == self.door.id
        )

        self.assertTrue(door.has_trap)
        self.assertIs(door.trap_state, TrapState.TRIGGERED)

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

    def test_unknown_room_map_node_never_renders_its_name(self) -> None:
        def unknown_map(display_name: str) -> PlayerMap:
            room = PlayerMapRoom(
                "sealed",
                "floor",
                display_name,
                100,
                100,
                1,
                1,
                KnowledgeState.KNOWN,
                is_focused=True,
            )
            return PlayerMap(
                1,
                "dungeon",
                Floor("floor", "dungeon", 1, "Floor 1"),
                None,
                "sealed",
                (room,),
                (),
            )

        first = render_player_map(unknown_map("? Sealed Vault"))
        second = render_player_map(unknown_map("? Completely Different Secret"))

        self.assertEqual(first.getvalue(), second.getvalue())

    def test_new_connection_from_current_room_reveals_connector_and_unknown_room(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)

        connection = self.world.connect_rooms(
            self.entrance.id,
            "south",
            self.unknown.id,
            return_exit_name="north",
        )
        view = self.views.build_player_map(self.alice_id)

        unknown = next(room for room in view.rooms if room.id == self.unknown.id)
        self.assertEqual(unknown.knowledge_state, KnowledgeState.KNOWN)
        self.assertEqual(unknown.display_name, "? Sealed Vault")
        self.assertIn(connection.id, [item.id for item in view.connections])

    def test_new_hidden_connection_is_not_revealed_to_current_character(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)

        connection = self.world.connect_rooms(
            self.entrance.id,
            "secret",
            self.unknown.id,
            return_exit_name="hidden return",
            hidden=True,
        )
        view = self.views.build_player_map(self.alice_id)

        self.assertNotIn(connection.id, [item.id for item in view.connections])
        self.assertNotIn(self.unknown.id, [room.id for room in view.rooms])

    def test_closed_door_opens_automatically_when_walked_through_and_stays_open(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        connection = self.world.connect_rooms(
            self.entrance.id,
            "south",
            self.unknown.id,
            return_exit_name="north",
            connection_type=ConnectionType.DOOR,
            is_open=False,
        )

        closed_view = self.views.build_player_map(self.alice_id)
        self.assertNotIn(self.unknown.id, [room.id for room in closed_view.rooms])
        closed_door = next(
            item for item in closed_view.connections if item.id == connection.id
        )
        self.assertFalse(closed_door.is_open)
        self.assertEqual(render_player_map(closed_view).read(8), b"\x89PNG\r\n\x1a\n")

        self.world.move_character(self.alice_id, "south")
        opened_view = self.views.build_player_map(self.alice_id)
        self.assertTrue(
            next(item for item in opened_view.connections if item.id == connection.id).is_open
        )
        self.assertIn(self.unknown.id, [room.id for room in opened_view.rooms])
        remembered = next(
            room for room in opened_view.rooms if room.id == self.unknown.id
        )
        self.assertEqual(remembered.knowledge_state, KnowledgeState.VISITED)

    def test_ensure_location_knowledge_repairs_a_missing_current_room_connector(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        connection = self.world.connect_rooms(
            self.entrance.id,
            "south",
            self.unknown.id,
            return_exit_name="north",
        )
        with self.database._connect() as database_connection:
            database_connection.execute(
                "DELETE FROM character_known_connections "
                "WHERE character_id = ? AND connection_id = ?",
                (self.alice_id, connection.id),
            )
            database_connection.execute(
                "DELETE FROM character_room_knowledge "
                "WHERE character_id = ? AND room_id = ?",
                (self.alice_id, self.unknown.id),
            )

        self.database.ensure_character_location_knowledge(self.alice_id)
        view = self.views.build_player_map(self.alice_id)

        self.assertIn(connection.id, [item.id for item in view.connections])
        self.assertIn(self.unknown.id, [room.id for room in view.rooms])

    def test_layout_preserves_world_spacing_and_centers_focus(self) -> None:
        rooms = tuple(
            PlayerMapRoom(
                str(index),
                "floor",
                f"Room {index}",
                0,
                index * 200,
                1,
                1,
                KnowledgeState.VISITED,
                is_current=index == 0,
                is_focused=index == 0,
            )
            for index in range(4)
        )
        view = PlayerMap(
            1,
            "dungeon",
            Floor("floor", "dungeon", 1, "Floor 1"),
            "0",
            "0",
            rooms,
            (),
        )

        positions = _layout(view)
        centers = {
            room_id: (left + width / 2, top + height / 2)
            for room_id, (left, top, width, height) in positions.items()
        }
        viewport_center = (
            (VIEWPORT_BOUNDS[0] + VIEWPORT_BOUNDS[2]) / 2,
            (VIEWPORT_BOUNDS[1] + VIEWPORT_BOUNDS[3]) / 2,
        )

        self.assertEqual(centers["0"], viewport_center)
        for index in range(3):
            self.assertEqual(
                centers[str(index + 1)][1] - centers[str(index)][1],
                200 * WORLD_TO_MAP_SCALE,
            )
        self.assertGreater(positions["3"][1], MAP_HEIGHT)

    def test_layout_recenters_on_focused_room_without_moving_current(self) -> None:
        rooms = tuple(
            PlayerMapRoom(
                str(index),
                "floor",
                f"Room {index}",
                index * 120,
                index * 200,
                1,
                1,
                KnowledgeState.VISITED,
                is_current=index == 0,
                is_focused=index == 2,
            )
            for index in range(4)
        )
        view = PlayerMap(
            1,
            "dungeon",
            Floor("floor", "dungeon", 1, "Floor 1"),
            "0",
            "2",
            rooms,
            (),
        )

        positions = _layout(view)
        focus = positions["2"]
        current = positions["0"]
        viewport_center = (
            (VIEWPORT_BOUNDS[0] + VIEWPORT_BOUNDS[2]) / 2,
            (VIEWPORT_BOUNDS[1] + VIEWPORT_BOUNDS[3]) / 2,
        )

        self.assertEqual(
            (focus[0] + focus[2] / 2, focus[1] + focus[3] / 2),
            viewport_center,
        )
        self.assertEqual(
            focus[1] - current[1],
            400 * WORLD_TO_MAP_SCALE,
        )
        rendered = render_player_map(view)
        with Image.open(rendered) as image:
            current_center_x = round(current[0] + current[2] / 2)
            background = _map_canvas()
            try:
                self.assertEqual(
                    image.getpixel((current_center_x, 100)),
                    background.getpixel((current_center_x, 100)),
                )
            finally:
                background.close()

    def test_layout_moves_upper_room_to_preserve_full_vertical_door_size(self) -> None:
        rooms = (
            PlayerMapRoom(
                "upper", "floor", "Upper", 0, 0, 1, 1, KnowledgeState.VISITED
            ),
            PlayerMapRoom(
                "lower",
                "floor",
                "Lower",
                0,
                180,
                1,
                1,
                KnowledgeState.VISITED,
                is_current=True,
                is_focused=True,
            ),
        )
        connection = PlayerMapConnection(
            "door",
            "upper",
            "lower",
            "floor",
            "floor",
            ConnectionType.DOOR,
            True,
            has_lock=True,
        )
        view = PlayerMap(
            1,
            "dungeon",
            Floor("floor", "dungeon", 1, "Floor 1"),
            "lower",
            "lower",
            rooms,
            (connection,),
        )

        positions = _layout(view)
        upper = positions["upper"]
        lower = positions["lower"]
        door = _loaded_door_art()
        assert door is not None

        self.assertGreaterEqual(
            lower[1] - (upper[1] + upper[3]),
            door.height + CONNECTION_ROOM_GAP,
        )
        self.assertEqual(
            (lower[0] + lower[2] / 2, lower[1] + lower[3] / 2),
            (
                (VIEWPORT_BOUNDS[0] + VIEWPORT_BOUNDS[2]) / 2,
                (VIEWPORT_BOUNDS[1] + VIEWPORT_BOUNDS[3]) / 2,
            ),
        )

    def test_focus_fog_uses_graph_distance_without_changing_knowledge(self) -> None:
        rooms = tuple(
            PlayerMapRoom(
                str(index),
                "floor",
                f"Room {index}",
                0,
                index * 150,
                1,
                1,
                KnowledgeState.VISITED,
                is_focused=index == 0,
            )
            for index in range(5)
        )
        connections = tuple(
            PlayerMapConnection(
                str(index),
                str(index),
                str(index + 1),
                "floor",
                "floor",
                ConnectionType.PASSAGE,
                True,
            )
            for index in range(4)
        )
        view = PlayerMap(
            1,
            "dungeon",
            Floor("floor", "dungeon", 1, "Floor 1"),
            None,
            "0",
            rooms,
            connections,
        )

        self.assertEqual(
            _focus_distances(view),
            {str(index): index for index in range(5)},
        )
        self.assertEqual(
            [room.knowledge_state for room in view.rooms],
            [KnowledgeState.VISITED] * 5,
        )
        self.assertEqual(_fog_strength(0), 0)
        self.assertEqual(_fog_strength(1), 0)
        self.assertLess(_fog_strength(2), _fog_strength(3))
        self.assertLess(_fog_strength(3), _fog_strength(4))

    def test_visited_room_hud_uses_one_composed_card_without_duplicate_text(self) -> None:
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
            self.assertIsNone(detail.title)
            self.assertIsNone(detail.description)
            self.assertEqual(len(detail.fields), 0)
            self.assertEqual(detail.image.url, "attachment://room-card.webp")
            self.assertEqual(files[1].filename, "room-card.webp")
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
        self.assertIsNone(view.focused_room.scene_image_path)
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
            self.assertIsNone(detail.title)
            self.assertIsNone(detail.description)
            self.assertEqual(len(detail.fields), 0)
            self.assertEqual(detail.image.url, "attachment://room-card.webp")
            self.assertEqual(len(files), 2)
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
        recalled = self.views.build_player_map(self.alice_id).focused_room
        self.assertEqual(recalled.scene_image_path, self.entrance.scene_image_path)

    def test_missing_focus_defaults_room_preview_to_current_room(self) -> None:
        self.world.place_character(self.alice_id, self.entrance.id)
        with self.database._connect() as connection:
            connection.execute(
                "UPDATE player_view_states SET focused_room_id = NULL "
                "WHERE character_id = ?",
                (self.alice_id,),
            )

        view = self.views.build_player_map(self.alice_id)

        self.assertEqual(view.focused_room_id, self.entrance.id)
        self.assertEqual(view.focused_room.room_id, self.entrance.id)
        entrance = next(room for room in view.rooms if room.id == self.entrance.id)
        self.assertTrue(entrance.is_focused)

    def test_local_room_image_is_framed_for_a_visited_room(self) -> None:
        store = RoomImageStore(Path(self.temporary_directory.name) / "room_images")
        source = BytesIO()
        Image.new("RGB", (800, 450), "purple").save(source, format="PNG")
        key = store.save(source.getvalue(), "image/png")
        self.database.set_room_scene_image(self.chapel.id, key)
        self.world.place_character(self.alice_id, self.chapel.id)
        view = self.views.build_player_map(self.alice_id)
        adapter = DiscordPlayerViewAdapter(
            self.database, self.views, Mock(), room_images=store
        )

        embeds, files, _controls = adapter._message_parts(view)
        try:
            self.assertEqual(embeds[1].image.url, "attachment://room-card.webp")
            self.assertEqual(files[1].filename, "room-card.webp")
            self.assertIsNone(embeds[1].title)
            self.assertEqual(len(embeds[1].fields), 0)
        finally:
            for file in files:
                file.close()

    def test_visited_room_without_image_has_tasteful_fallback(self) -> None:
        self.database.set_room_scene_image(self.chapel.id, None)
        self.world.place_character(self.alice_id, self.chapel.id)
        view = self.views.build_player_map(self.alice_id)
        adapter = DiscordPlayerViewAdapter(self.database, self.views, Mock())

        embeds, files, _controls = adapter._message_parts(view)
        try:
            self.assertEqual(embeds[1].image.url, "attachment://room-card.webp")
            self.assertEqual(files[1].filename, "room-card.webp")
        finally:
            for file in files:
                file.close()

    def test_missing_room_image_file_does_not_break_player_view(self) -> None:
        self.database.set_room_scene_image(self.chapel.id, f"{'0' * 32}.webp")
        self.world.place_character(self.alice_id, self.chapel.id)
        view = self.views.build_player_map(self.alice_id)
        adapter = DiscordPlayerViewAdapter(self.database, self.views, Mock())

        embeds, files, _controls = adapter._message_parts(view)
        try:
            self.assertEqual(embeds[1].image.url, "attachment://room-card.webp")
            self.assertEqual(files[1].filename, "room-card.webp")
        finally:
            for file in files:
                file.close()

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

    def test_room_and_item_changes_queue_live_map_refreshes(self) -> None:
        self.views.bind_discord_channel(self.alice_id, 77)
        self.world.place_character(self.alice_id, self.entrance.id)
        self.database.clear_player_map_refresh(self.alice_id)

        self.world.place_character(self.bob_id, self.entrance.id)

        self.assertEqual(
            self.database.pending_player_map_refreshes(), (self.alice_id,)
        )
        self.database.clear_player_map_refresh(self.alice_id)

        self.world.create_item("key", "Iron Key")
        self.world.place_item(InventoryHolder.room(self.entrance.id), "key")

        self.assertEqual(
            self.database.pending_player_map_refreshes(), (self.alice_id,)
        )

    def test_room_image_change_refreshes_a_previously_visited_focus(self) -> None:
        self.views.bind_discord_channel(self.alice_id, 77)
        self.world.place_character(self.alice_id, self.entrance.id)
        self.world.move_character(self.alice_id, "east")
        self.views.focus_room(self.alice_id, self.entrance.id)
        self.database.clear_player_map_refresh(self.alice_id)

        self.database.set_room_scene_image(self.entrance.id, "memory.webp")

        self.assertEqual(
            self.database.pending_player_map_refreshes(), (self.alice_id,)
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
