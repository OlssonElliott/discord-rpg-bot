import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from rpg_bot.commands.inventory import (
    InventoryCommands,
    forget_open_inventory,
)
from rpg_bot.commands.world import WorldCommands
from rpg_bot.database import Database
from rpg_bot.portraits import CharacterPortraitStore
from rpg_bot.world import InventoryHolder


class WorldCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_directory.name) / "world-commands.db")
        self.database.initialize()
        character = self.database.create_character(7, "Olof", 15)
        self.character_id = character.character_id
        self.cog = WorldCommands(self.database)
        area = self.cog.world.create_area("chapel", "Ruined Chapel")
        room = self.cog.world.create_room("entrance", area.id, "Entrance")
        self.cog.world.place_character(self.character_id, room.id)
        self.cog.world.create_item("copper", "Copper Coin")
        self.cog.world.create_item("rusty_key", "Rusty Key", stackable=False)
        self.cog.world.place_item(InventoryHolder.room(room.id), "copper", 3)
        self.cog.world.place_item(InventoryHolder.room(room.id), "rusty_key")
        self.interaction = SimpleNamespace(user=SimpleNamespace(id=7))

    def tearDown(self) -> None:
        forget_open_inventory(7)
        self.temp_directory.cleanup()

    @staticmethod
    def command_interaction(user_id: int = 7) -> tuple[SimpleNamespace, SimpleNamespace]:
        message = SimpleNamespace(edit=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=user_id),
            message=message,
            original_response=AsyncMock(return_value=message),
            edit_original_response=AsyncMock(),
            response=SimpleNamespace(
                send_message=AsyncMock(),
                edit_message=AsyncMock(),
            ),
        )
        return interaction, message

    async def test_take_autocomplete_lists_loose_items_with_quantities(self) -> None:
        choices = await self.cog.loose_item_autocomplete(self.interaction, "")

        self.assertEqual(
            [(choice.name, choice.value) for choice in choices],
            [("Copper Coin (3 here)", "copper"), ("Rusty Key (1 here)", "rusty_key")],
        )

    async def test_take_autocomplete_filters_by_name_or_id(self) -> None:
        by_name = await self.cog.loose_item_autocomplete(self.interaction, "coin")
        by_id = await self.cog.loose_item_autocomplete(self.interaction, "rusty_")

        self.assertEqual([choice.value for choice in by_name], ["copper"])
        self.assertEqual([choice.value for choice in by_id], ["rusty_key"])

    async def test_take_autocomplete_is_empty_without_an_active_room(self) -> None:
        choices = await self.cog.loose_item_autocomplete(
            SimpleNamespace(user=SimpleNamespace(id=999)), ""
        )

        self.assertEqual(choices, [])

    async def test_move_autocomplete_lists_reachable_room_and_exit_name(self) -> None:
        hall = self.cog.world.create_room("hall", "chapel", "Collapsed Hall")
        self.cog.world.connect_rooms("entrance", "north", hall.id)
        self.cog.world.place_character(self.character_id, "entrance")

        choices = await self.cog.move_destination_autocomplete(
            self.interaction, ""
        )

        self.assertEqual(
            [(choice.name, choice.value) for choice in choices],
            [("Collapsed Hall — via north", "north")],
        )

    async def test_move_autocomplete_lists_previous_room_for_two_way_passage(self) -> None:
        hall = self.cog.world.create_room("hall", "chapel", "Collapsed Hall")
        self.cog.world.connect_rooms(
            "entrance", "north", hall.id, return_exit_name="south"
        )
        self.cog.world.place_character(self.character_id, "entrance")
        self.cog.world.move_character(self.character_id, "north")

        choices = await self.cog.move_destination_autocomplete(
            self.interaction, ""
        )

        self.assertEqual(
            [(choice.name, choice.value) for choice in choices],
            [("Entrance — via south", "south")],
        )

    async def test_move_autocomplete_filters_by_room_exit_or_id(self) -> None:
        hall = self.cog.world.create_room("old_hall", "chapel", "Collapsed Hall")
        self.cog.world.connect_rooms("entrance", "north", hall.id)
        self.cog.world.place_character(self.character_id, "entrance")

        by_room = await self.cog.move_destination_autocomplete(
            self.interaction, "collapsed"
        )
        by_exit = await self.cog.move_destination_autocomplete(
            self.interaction, "north"
        )
        by_id = await self.cog.move_destination_autocomplete(
            self.interaction, "old_"
        )

        self.assertEqual([choice.value for choice in by_room], ["north"])
        self.assertEqual([choice.value for choice in by_exit], ["north"])
        self.assertEqual([choice.value for choice in by_id], ["north"])

    async def test_move_autocomplete_does_not_reveal_hidden_connection(self) -> None:
        vault = self.cog.world.create_room("vault", "chapel", "Sealed Vault")
        self.cog.world.connect_rooms(
            "entrance", "hidden panel", vault.id, hidden=True
        )
        self.cog.world.place_character(self.character_id, "entrance")

        choices = await self.cog.move_destination_autocomplete(
            self.interaction, ""
        )

        self.assertEqual(choices, [])

    async def test_take_names_character_and_refreshes_open_inventory(self) -> None:
        self.cog.world.create_item("health_potion", "Health Potion")
        room = self.cog.world.get_character_room(self.character_id)
        self.cog.world.place_item(InventoryHolder.room(room.id), "health_potion")
        inventory_cog = InventoryCommands(self.database)
        inventory_interaction, message = self.command_interaction()
        await inventory_cog.inventory.callback(
            inventory_cog.inventory.binding, inventory_interaction
        )
        take_interaction, _ = self.command_interaction()

        await self.cog.take.callback(
            self.cog.take.binding, take_interaction, "health_potion", 1
        )

        public_embed = take_interaction.response.send_message.await_args.kwargs[
            "embed"
        ]
        self.assertEqual(public_embed.author.name, "Olof")
        self.assertEqual(public_embed.description, "Took **1 × Health Potion**.")
        inventory_interaction.edit_original_response.assert_awaited_once()
        refreshed = inventory_interaction.edit_original_response.await_args.kwargs[
            "embeds"
        ][0]
        items = next(
            field.value for field in refreshed.fields if field.name == "Inventory"
        )
        self.assertIn("Health Potion", items)

    async def test_public_world_action_attaches_character_portrait(self) -> None:
        portrait_root = Path(self.temp_directory.name) / "portraits"
        portrait_path = portrait_root / str(self.character_id) / "portrait.webp"
        portrait_path.parent.mkdir(parents=True)
        portrait_path.write_bytes(b"portrait")
        self.database.set_character_portrait(
            7, self.character_id, f"{self.character_id}/portrait.webp"
        )
        cog = WorldCommands(
            self.database,
            portrait_store=CharacterPortraitStore(portrait_root),
        )
        interaction, _message = self.command_interaction()

        await cog.room.callback(cog.room.binding, interaction)

        call = interaction.response.send_message.await_args
        self.assertEqual(call.kwargs["embed"].author.name, "Olof")
        self.assertEqual(
            call.kwargs["embed"].thumbnail.url,
            "attachment://character_portrait.webp",
        )
        self.assertEqual(call.kwargs["file"].filename, "character_portrait.webp")

    async def test_map_creates_private_read_only_channel_and_persistent_hud(self) -> None:
        channel = SimpleNamespace(
            id=88,
            mention="#map-olof",
            send=AsyncMock(return_value=SimpleNamespace(id=900)),
            fetch_message=AsyncMock(),
        )
        user = MagicMock()
        user.id = 7
        default_role = MagicMock()
        bot_member = MagicMock()
        guild = MagicMock()
        guild.me = bot_member
        guild.default_role = default_role
        guild.get_channel.return_value = None
        guild.create_text_channel = AsyncMock(return_value=channel)
        client = MagicMock()
        client.get_channel.return_value = channel
        client.fetch_channel = AsyncMock()
        response = SimpleNamespace(
            defer=AsyncMock(),
            send_message=AsyncMock(),
            is_done=MagicMock(return_value=True),
        )
        followup = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            user=user,
            guild=guild,
            client=client,
            response=response,
            followup=followup,
        )

        await self.cog.map.callback(self.cog.map.binding, interaction)

        response.defer.assert_awaited_once_with(ephemeral=True)
        guild.create_text_channel.assert_awaited_once()
        create_arguments = guild.create_text_channel.await_args
        self.assertEqual(create_arguments.args[0], "map-olof")
        player_permissions = create_arguments.kwargs["overwrites"][user]
        self.assertTrue(player_permissions.view_channel)
        self.assertFalse(player_permissions.send_messages)
        bot_permissions = create_arguments.kwargs["overwrites"][bot_member]
        self.assertTrue(bot_permissions.send_messages)
        self.assertIsNone(bot_permissions.manage_messages)
        channel.send.assert_awaited_once()
        sent = channel.send.await_args.kwargs
        self.assertEqual(len(sent["embeds"]), 2)
        self.assertEqual(sent["embeds"][0].image.url, "attachment://dungeon-map.png")
        self.assertEqual(sent["files"][0].filename, "dungeon-map.png")
        self.assertIsNotNone(sent["view"])
        state = self.database.get_player_view_state(self.character_id)
        self.assertEqual(
            (state.discord_channel_id, state.discord_message_id), (88, 900)
        )
        self.assertIn("#map-olof", followup.send.await_args.args[0])

    async def test_map_reuses_existing_channel_and_message(self) -> None:
        self.cog.player_views.bind_discord_channel(self.character_id, 88)
        self.database.update_player_view_state(
            self.character_id, discord_message_id=900
        )
        message = SimpleNamespace(edit=AsyncMock())
        channel = SimpleNamespace(
            id=88,
            mention="#map-olof",
            fetch_message=AsyncMock(return_value=message),
        )
        guild = MagicMock()
        guild.get_channel.return_value = channel
        user = MagicMock()
        user.id = 7
        client = MagicMock()
        client.get_channel.return_value = channel
        response = SimpleNamespace(
            defer=AsyncMock(),
            send_message=AsyncMock(),
            is_done=MagicMock(return_value=True),
        )
        interaction = SimpleNamespace(
            user=user,
            guild=guild,
            client=client,
            response=response,
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await self.cog.map.callback(self.cog.map.binding, interaction)

        guild.create_text_channel.assert_not_called()
        channel.fetch_message.assert_awaited_once_with(900)
        message.edit.assert_awaited_once()

    async def test_movement_automatically_refreshes_existing_map(self) -> None:
        destination = self.cog.world.create_room(
            "hall", "chapel", "Collapsed Hall"
        )
        self.cog.world.connect_rooms("entrance", "north", destination.id)
        self.cog.player_views.bind_discord_channel(self.character_id, 88)
        self.cog.map_messages = SimpleNamespace(refresh=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=7),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        await self.cog.move.callback(
            self.cog.move.binding, interaction, "north"
        )

        self.cog.map_messages.refresh.assert_awaited_once_with(self.character_id)
        self.assertEqual(
            self.cog.world.get_character_room(self.character_id).id,
            destination.id,
        )

    async def test_map_reports_missing_manage_channels_permission(self) -> None:
        user = MagicMock()
        user.id = 7
        bot_member = MagicMock()
        bot_member.guild_permissions.manage_channels = False
        guild = MagicMock()
        guild.me = bot_member
        guild.get_channel.return_value = None
        response = SimpleNamespace(
            defer=AsyncMock(),
            send_message=AsyncMock(),
            is_done=MagicMock(return_value=True),
        )
        followup = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            user=user,
            guild=guild,
            client=MagicMock(),
            response=response,
            followup=followup,
        )

        await self.cog.map.callback(self.cog.map.binding, interaction)

        guild.create_text_channel.assert_not_called()
        self.assertIn(
            "Manage Channels", followup.send.await_args.args[0]
        )


if __name__ == "__main__":
    unittest.main()
