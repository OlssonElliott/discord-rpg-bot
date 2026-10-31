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
    async def test_publishing_and_updating_reuses_one_message(self) -> None:
        from rpg_bot.map_renderer.combat import render_combat_map

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
        message = SimpleNamespace(
            id=555,
            edit=AsyncMock(),
        )
        channel = SimpleNamespace(
            id=444, send=AsyncMock(return_value=message),
        )
        message.channel = channel
        message.edit.return_value = message
        guild = SimpleNamespace(id=44)
        store = SimpleNamespace(
            get=Mock(return_value=None),
            save=Mock(),
        )
        fake_cog = SimpleNamespace(
            _scene_messages={},
            _last_scenes={},
            message_store=store,
            world=SimpleNamespace(
                get_room=lambda _: SimpleNamespace(name="Long Hall")
            ),
        )
        with patch(
            "rpg_bot.commands.combat.CombatOpenView",
            return_value=object(),
        ):
            await CombatCommands._publish_scene(
                fake_cog, guild, scene, channel=channel,
            )
            channel.send.assert_awaited_once()
            first = channel.send.await_args.kwargs
            first_name = first["file"].filename
            self.assertRegex(first_name, r"^combat-map-[0-9a-f]{12}\.png$")
            self.assertEqual(
                first["embed"].image.url,
                f"attachment://{first_name}",
            )
            store.save.assert_called_once_with(44, 22, 444, 555)

            changed = __import__("dataclasses").replace(
                scene,
                combatants=(
                    __import__("dataclasses").replace(
                        actor, movement_remaining=1,
                    ),
                ),
            )
            await CombatCommands._publish_scene(
                fake_cog, guild, changed, channel=channel,
            )
            channel.send.assert_awaited_once()  # No duplicate combat posts.
            message.edit.assert_awaited_once()
            updated = message.edit.await_args.kwargs
            self.assertEqual(len(updated["attachments"]), 1)
            updated_name = updated["attachments"][0].filename
            self.assertRegex(updated_name, r"^combat-map-[0-9a-f]{12}\.png$")
            self.assertEqual(updated["embed"].image.url, f"attachment://{updated_name}")
            self.assertEqual(fake_cog._scene_messages[44], message)

    def test_embed_only_contains_player_facing_status(self) -> None:
        scene = CombatScene(
            id=22, guild_id=44, room_id="hall", status=CombatStatus.ACTIVE,
            landmarks=(CombatLandmark("pillar", "Stone Pillar", x=0.1, y=0.2),),
            routes=(),
            combatants=(
                CombatantState(CombatantKind.CHARACTER, "11", "Sture", "pillar"),
            ),
        )
        embed = combat_scene_embed(scene, "Long Hall")
        self.assertEqual([field.name for field in embed.fields], ["Turn order"])
        self.assertEqual(embed.image.url, "attachment://combat-map.png")
        self.assertNotIn("Landmarks", str(embed.to_dict()))



if __name__ == "__main__":
    unittest.main()
