import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from rpg_bot.commands.combat import CombatCommands, combat_scene_embed, ensure_combat_channel
from rpg_bot.commands.combat_views import (
    CombatActionView,
    move_destinations,
)
from rpg_bot.combat.models import (
    CombatantKind, CombatantState, CombatLandmark, CombatRoute,
    CombatScene, CombatStatus, CoverLevel, LandmarkDistance,
    LandmarkRelation,
)
from rpg_bot.discord_support.combat_messages import CombatMessageStore


class CombatChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_combat_channel_is_reused(self) -> None:
        channel = SimpleNamespace(name="combat")
        guild = SimpleNamespace(
            id=44,
            text_channels=[channel],
            create_text_channel=AsyncMock(),
        )

        resolved = await ensure_combat_channel(guild)

        self.assertIs(resolved, channel)
        guild.create_text_channel.assert_not_awaited()

    async def test_combat_channel_is_created_once_when_missing(self) -> None:
        channel = SimpleNamespace(name="combat")
        guild = SimpleNamespace(
            id=44,
            text_channels=[],
            me=SimpleNamespace(
                guild_permissions=SimpleNamespace(manage_channels=True)
            ),
            create_text_channel=AsyncMock(return_value=channel),
        )

        resolved = await ensure_combat_channel(guild)

        self.assertIs(resolved, channel)
        guild.create_text_channel.assert_awaited_once_with(
            "combat",
            topic="Shared landmark-based combat scene and turn state.",
            reason="Public Rollkeeper combat channel",
        )


class CombatMessageStoreTests(unittest.TestCase):
    def test_saved_dashboard_message_survives_reinitialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "combat.db"
            first = CombatMessageStore(db_path)
            self.assertIsNone(first.get(44))
            first.save(44, 7, 111, 222)
            second = CombatMessageStore(db_path)
            entry = second.get(44)
            self.assertIsNotNone(entry)
            self.assertEqual((entry.scene_id, entry.channel_id, entry.message_id), (7, 111, 222))
            second.save(44, 8, 111, 333)
            self.assertEqual(first.get(44).message_id, 333)
            first.clear(44)
            self.assertIsNone(second.get(44))



class CombatMoveDestinationsTests(unittest.TestCase):
    def setUp(self):
        self.actor = CombatantState(
            CombatantKind.CHARACTER, "11", "Sture", "center",
            movement_remaining=3,
        )
        self.scene = CombatScene(
            id=9, guild_id=44, room_id="hall",
            status=CombatStatus.ACTIVE,
            landmarks=(
                CombatLandmark("center", "Room Center"),
                CombatLandmark("pillar", "Stone Pillar", cover=CoverLevel.HALF),
                CombatLandmark("door", "North Door"),
                CombatLandmark("blocked", "Blocked Door"),
            ),
            routes=(
                CombatRoute("center", "pillar", LandmarkDistance.NEAR),
                CombatRoute("pillar", "door", LandmarkDistance.FAR),
                CombatRoute(
                    "center", "blocked", LandmarkDistance.NEAR,
                    base_blocked=True,
                ),
            ),
            combatants=(self.actor,),
            current_turn_kind=CombatantKind.CHARACTER,
            current_turn_source_id="11",
        )

    def test_connected_destinations_use_engine_movement_cost(self):
        destinations = move_destinations(self.scene, self.actor)
        by_location = {
            (option.landmark_id, option.relation): option.cost
            for option in destinations
        }
        self.assertEqual(
            by_location[("pillar", LandmarkRelation.AT)], 2,
        )
        self.assertNotIn(
            ("pillar", LandmarkRelation.BEHIND), by_location,
        )
        # A longer route is offered so the engine can move partway.
        self.assertEqual(
            by_location[("door", LandmarkRelation.AT)], 5,
        )
        self.assertNotIn(
            ("blocked", LandmarkRelation.AT), by_location,
        )
        self.assertNotIn(
            ("center", LandmarkRelation.AT), by_location,
        )

    def test_no_remaining_movement_blocks_nonzero_routes(self):
        from dataclasses import replace

        stationary = replace(self.actor, movement_remaining=0)
        self.assertEqual(move_destinations(self.scene, stationary), [])

    def test_do_not_offer_distant_locations_after_movement_runs_out(self):
        from dataclasses import replace

        # center -> pillar costs 2, pillar -> door costs 3.
        # At 2 MP the player reaches pillar, but cannot begin moving
        # toward door, so door must not be listed as PARTIAL.
        limited = replace(self.actor, movement_remaining=2)
        costs = {
            destination.landmark_id: destination.cost
            for destination in move_destinations(self.scene, limited)
        }
        self.assertEqual(costs, {"pillar": 2})

        # At 3 MP, the player can spend 1 MP on the pillar -> door
        # connection; door is therefore a legitimate PARTIAL option.
        with_progress = replace(self.actor, movement_remaining=3)
        costs = {
            destination.landmark_id: destination.cost
            for destination in move_destinations(self.scene, with_progress)
        }
        self.assertEqual(costs, {"pillar": 2, "door": 5})

    def test_multi_route_preview_never_lists_locations_beyond_partial_leg(self):
        from dataclasses import replace

        scene = replace(
            self.scene,
            landmarks=(
                CombatLandmark("center", "Room Center"),
                CombatLandmark("pillar", "Stone Pillar"),
                CombatLandmark("door", "North Door"),
                CombatLandmark("far_end", "Far End"),
            ),
            routes=(
                CombatRoute("center", "pillar", LandmarkDistance.NEAR),
                CombatRoute("pillar", "door", LandmarkDistance.NEAR),
                CombatRoute("door", "far_end", LandmarkDistance.NEAR),
            ),
        )
        limited = replace(self.actor, movement_remaining=3)
        costs = {
            destination.landmark_id: destination.cost
            for destination in move_destinations(scene, limited)
        }
        self.assertEqual(costs, {"pillar": 2, "door": 4})
        self.assertNotIn("far_end", costs)

    def test_partial_movement_from_route_only_lists_nearest_approachable_nodes(self):
        from dataclasses import replace

        scene = replace(
            self.scene,
            landmarks=(
                CombatLandmark("center", "Room Center"),
                CombatLandmark("pillar", "Stone Pillar"),
                CombatLandmark("door", "North Door"),
                CombatLandmark("far_end", "Far End"),
            ),
            routes=(
                CombatRoute("center", "pillar", LandmarkDistance.NEAR),
                CombatRoute("pillar", "door", LandmarkDistance.NEAR),
                CombatRoute("door", "far_end", LandmarkDistance.NEAR),
            ),
        )
        mid_route = replace(
            self.actor,
            route_source_landmark_id="center",
            route_destination_landmark_id="pillar",
            route_progress=1,
            route_cost=2,
            movement_remaining=2,
        )
        costs = {
            destination.landmark_id: destination.cost
            for destination in move_destinations(scene, mid_route)
        }
        self.assertEqual(costs["pillar"], 1)
        self.assertEqual(costs["door"], 3)
        self.assertNotIn("far_end", costs)

    def test_partial_route_options_use_remaining_distance(self):
        from dataclasses import replace

        between = replace(
            self.actor,
            landmark_id="center",
            route_source_landmark_id="center",
            route_destination_landmark_id="pillar",
            route_progress=1,
            route_cost=2,
            movement_remaining=1,
        )
        locations = {
            destination.landmark_id: destination.cost
            for destination in move_destinations(self.scene, between)
        }
        self.assertEqual(locations["pillar"], 1)
        self.assertEqual(locations["center"], 1)


class CombatMoveAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_active_character_owner_can_open_move(self):
        from rpg_bot.commands.combat_views import CombatMoveView

        actor = CombatantState(
            CombatantKind.CHARACTER, "11", "Sture", "center",
        )
        scene = CombatScene(
            id=9, guild_id=44, room_id="hall", status=CombatStatus.ACTIVE,
            combatants=(actor,),
            current_turn_kind=CombatantKind.CHARACTER,
            current_turn_source_id="11",
        )
        database = SimpleNamespace(
            get_character=lambda user_id: (
                SimpleNamespace(character_id=11) if user_id == 7 else None
            ),
        )
        cog = SimpleNamespace(
            service=SimpleNamespace(current=lambda _: scene),
            database=database,
        )
        authorized = SimpleNamespace(
            guild_id=44, user=SimpleNamespace(id=7),
        )
        outsider = SimpleNamespace(
            guild_id=44, user=SimpleNamespace(id=8),
        )
        view = CombatActionView(cog, scene_id=9, character_id="11")
        self.assertEqual(view._check(authorized)[1].name, "Sture")

        from rpg_bot.combat.service import CombatError

        with self.assertRaises(CombatError):
            view._check(outsider)
        with self.assertRaises(CombatError):
            CombatMoveView(cog, scene_id=999, character_id="11", destinations=[])._check(authorized)



class CombatDiscordMapPublishingTests(unittest.IsolatedAsyncioTestCase):
    async def test_publishing_turn_transition_keeps_history_and_moves_map_to_bottom(self) -> None:
        import sqlite3
        from rpg_bot.discord_support.combat_events import CombatEventArchiveStore

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "combat.db"
            with sqlite3.connect(path) as db:
                db.executescript(
                    """
                    CREATE TABLE combat_log_entries (
                        id INTEGER PRIMARY KEY, scene_id INTEGER,
                        round_number INTEGER, event_type TEXT,
                        actor_kind TEXT, actor_source_id TEXT,
                        actor_name TEXT, message TEXT, created_at TEXT
                    );
                    INSERT INTO combat_log_entries VALUES
                        (1,22,1,'turn_started','character','11','Sture','start','t1'),
                        (2,22,1,'combatant_moved','character','11','Sture',
                         'Sture moved to Stone Pillar','t2');
                    """
                )
            actor = CombatantState(
                CombatantKind.CHARACTER, "11", "Sture", "pillar",
            )
            scene = CombatScene(
                id=22, guild_id=44, room_id="hall", status=CombatStatus.ACTIVE,
                landmarks=(CombatLandmark("pillar", "Stone Pillar"),),
                combatants=(actor,),
                current_turn_kind=CombatantKind.CHARACTER,
                current_turn_source_id="11",
            )

            sent = []
            channel = SimpleNamespace(id=444)
            async def send(**kwargs):
                msg = SimpleNamespace(
                    id=555 + len(sent),
                    channel=channel,
                    edit=AsyncMock(),
                )
                msg.edit.return_value = msg
                sent.append((msg, kwargs))
                return msg
            channel.send = AsyncMock(side_effect=send)
            channel.fetch_message = AsyncMock(
                side_effect=lambda mid: next(msg for msg, _ in sent if msg.id == mid)
            )
            guild = SimpleNamespace(
                id=44,
                get_channel=lambda channel_id: channel if channel_id == 444 else None,
            )
            cog = CombatCommands.__new__(CombatCommands)
            cog._scene_messages = {}
            cog._last_scenes = {}
            cog._publish_locks = {}
            cog.message_store = CombatMessageStore(path)
            cog.archive_store = CombatEventArchiveStore(path)
            cog.world = SimpleNamespace(
                get_room=lambda _: SimpleNamespace(name="Long Hall"),
            )

            with patch(
                "rpg_bot.commands.combat.CombatOpenView",
                return_value=object(),
            ):
                await CombatCommands._publish_scene(
                    cog, guild, scene, channel=channel,
                )
                self.assertEqual(len(sent), 1)
                self.assertTrue(sent[0][1]["silent"])
                self.assertEqual(sent[0][1]["file"].filename[:11], "combat-map-")
                self.assertEqual(cog.message_store.get(44).turn_marker_id, 1)

                with sqlite3.connect(path) as db:
                    db.execute(
                        "INSERT INTO combat_log_entries VALUES "
                        "(3,22,1,'turn_started','enemy','bandit','Bandit',"
                        "'Bandit turn began','t3')"
                    )
                next_scene = __import__("dataclasses").replace(
                    scene,
                    combatants=(
                        CombatantState(CombatantKind.ENEMY, "bandit", "Bandit", "pillar"),
                    ),
                    current_turn_kind=CombatantKind.ENEMY,
                    current_turn_source_id="bandit",
                )
                await CombatCommands._publish_scene(
                    cog, guild, next_scene, channel=channel,
                )
                self.assertEqual(len(sent), 2)
                sent[0][0].edit.assert_awaited_once()
                summary = sent[0][0].edit.await_args.kwargs
                self.assertEqual(summary["attachments"], [])
                self.assertIsNone(summary["view"])
                self.assertIn("Sture", summary["embed"].title)
                self.assertIn("Sture moved", summary["embed"].description)
                self.assertTrue(sent[1][1]["silent"])
                self.assertEqual(cog.message_store.get(44).turn_marker_id, 3)

                # State updates within the same turn edit the current map.
                await CombatCommands._publish_scene(
                    cog, guild, next_scene, channel=channel,
                )
                self.assertEqual(len(sent), 2)
                sent[1][0].edit.assert_awaited_once()

    def test_embed_only_contains_player_facing_status(self) -> None:
        scene = CombatScene(
            id=22, guild_id=44, room_id="hall", status=CombatStatus.ACTIVE,
            landmarks=(CombatLandmark("pillar", "Stone Pillar", x=0.1, y=0.2),),
            routes=(),
            combatants=(
                CombatantState(CombatantKind.CHARACTER, "11", "Sture", "pillar"),
            ),
            current_turn_kind=CombatantKind.CHARACTER,
            current_turn_source_id="11",
        )
        embed = combat_scene_embed(scene, "Long Hall")
        self.assertEqual([field.name for field in embed.fields], ["Turn order", "Current turn · Sture"])
        self.assertEqual(embed.image.url, "attachment://combat-map.png")
        self.assertNotIn("Landmarks", str(embed.to_dict()))


if __name__ == "__main__":
    unittest.main()
