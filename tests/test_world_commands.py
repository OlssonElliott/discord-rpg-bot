import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from rpg_bot.commands.inventory import (
    InventoryCommands,
    forget_open_inventory,
)
from rpg_bot.commands.world import WorldCommands
from rpg_bot.database import Database
from rpg_bot.dungeon import ConnectionType, TrapDamageType, TrapState
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
        game_channel = SimpleNamespace(
            name="game", mention="#game", send=AsyncMock()
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=user_id),
            guild=SimpleNamespace(text_channels=[game_channel]),
            message=message,
            original_response=AsyncMock(return_value=message),
            edit_original_response=AsyncMock(),
            response=SimpleNamespace(
                send_message=AsyncMock(),
                edit_message=AsyncMock(),
                defer=AsyncMock(),
            ),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        return interaction, message

    def give_tool(self, template_id: str) -> None:
        with self.database._connect() as connection:
            connection.execute(
                """
                INSERT INTO character_items (
                    instance_id, character_id, template_id, quantity, durability
                ) VALUES (?, ?, ?, 1, NULL)
                """,
                (f"{template_id}-instance", self.character_id, template_id),
            )

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

    async def test_move_autocomplete_uses_only_exit_name_for_unknown_room(self) -> None:
        vault = self.cog.world.create_room("vault", "chapel", "Sealed Vault")
        self.cog.world.place_character(self.character_id, "entrance")
        self.cog.world.connect_rooms(
            "entrance",
            "north",
            vault.id,
            connection_type=ConnectionType.DOOR,
            is_open=False,
        )

        choices = await self.cog.move_destination_autocomplete(
            self.interaction, ""
        )
        guessed_name = await self.cog.move_destination_autocomplete(
            self.interaction, "sealed"
        )
        guessed_id = await self.cog.move_destination_autocomplete(
            self.interaction, "vault"
        )

        self.assertEqual(
            [(choice.name, choice.value) for choice in choices],
            [("North", "north")],
        )
        self.assertEqual(guessed_name, [])
        self.assertEqual(guessed_id, [])

    async def test_door_autocomplete_lists_only_door_exits(self) -> None:
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        yard = self.cog.world.create_room("yard", "chapel", "Yard")
        self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            connection_type=ConnectionType.DOOR,
            is_open=False,
        )
        self.cog.world.connect_rooms("entrance", "east", yard.id)

        choices = await self.cog.door_exit_autocomplete(self.interaction, "")

        self.assertEqual(
            [(choice.name, choice.value) for choice in choices],
            [("North", "north")],
        )

    async def test_door_commands_open_and_close_from_either_side(self) -> None:
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        connection = self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            return_exit_name="south",
            connection_type=ConnectionType.DOOR,
            is_open=False,
        )
        open_interaction, _ = self.command_interaction()

        await self.cog.door_open.callback(
            self.cog.door_open.binding, open_interaction, "north"
        )

        opened = next(
            item
            for item in self.database.list_known_connections(self.character_id)
            if item.id == connection.id
        )
        self.assertTrue(opened.is_open)
        open_embed = open_interaction.guild.text_channels[0].send.await_args.kwargs[
            "embed"
        ]
        self.assertEqual(open_embed.description, "Olof opens the door.")
        open_interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        open_interaction.followup.send.assert_awaited_once_with(
            "Door interaction resolved. Posted in #game.", ephemeral=True
        )

        self.cog.world.move_character(self.character_id, "north")
        close_interaction, _ = self.command_interaction()
        await self.cog.door_close.callback(
            self.cog.door_close.binding, close_interaction, "south"
        )

        closed = next(
            item
            for item in self.database.list_known_connections(self.character_id)
            if item.id == connection.id
        )
        self.assertFalse(closed.is_open)
        close_embed = close_interaction.guild.text_channels[0].send.await_args.kwargs[
            "embed"
        ]
        self.assertEqual(close_embed.description, "Olof closes the door.")

    async def test_door_open_locked_door_fails_with_flavor_message(self) -> None:
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        connection = self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            connection_type=ConnectionType.DOOR,
            has_lock=True,
            is_locked=True,
            unlock_difficulty=12,
        )
        interaction, _ = self.command_interaction()

        await self.cog.door_open.callback(
            self.cog.door_open.binding, interaction, "north"
        )

        persisted = next(
            item
            for item in self.database.list_known_connections(self.character_id)
            if item.id == connection.id
        )
        self.assertFalse(persisted.is_open)
        embed = interaction.guild.text_channels[0].send.await_args.kwargs["embed"]
        self.assertEqual(
            embed.description, "Olof tries to open the door, but it is locked."
        )

    async def test_lockpick_succeeds_without_stealth_tree(self) -> None:
        self.give_tool("lockpicks")
        with self.database._connect() as connection:
            connection.execute(
                "UPDATE characters SET dexterity = 20 WHERE id = ?",
                (self.character_id,),
            )
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        door = self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            connection_type=ConnectionType.DOOR,
            has_lock=True,
            is_locked=True,
            unlock_difficulty=6,
        )
        interaction, _ = self.command_interaction()

        await self.cog.lockpick.callback(
            self.cog.lockpick.binding, interaction, "north"
        )

        persisted = next(
            item
            for item in self.database.list_known_connections(self.character_id)
            if item.id == door.id
        )
        self.assertTrue(persisted.has_lock)
        self.assertFalse(persisted.is_locked)
        embed = interaction.guild.text_channels[0].send.await_args.kwargs["embed"]
        self.assertEqual(
            embed.description,
            "Olof works at the lock until it gives with a quiet click.",
        )
        confirmation = interaction.followup.send.await_args.args[0]
        self.assertIn("Lockpick succeeded:", confirmation)
        self.assertIn("Dexterity +5", confirmation)
        self.assertNotIn("Stealth", confirmation)

    async def test_lockpick_succeeds_from_reverse_side_of_bidirectional_door(self) -> None:
        self.give_tool("lockpicks")
        with self.database._connect() as connection:
            connection.execute(
                "UPDATE characters SET dexterity = 20 WHERE id = ?",
                (self.character_id,),
            )
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        door = self.cog.world.connect_rooms(
            "entrance",
            "east",
            hall.id,
            return_exit_name="west",
            connection_type=ConnectionType.DOOR,
            has_lock=True,
            is_locked=True,
            unlock_difficulty=6,
        )
        self.cog.world.place_character(self.character_id, hall.id)
        interaction, _ = self.command_interaction()

        await self.cog.lockpick.callback(
            self.cog.lockpick.binding, interaction, "west"
        )

        persisted = next(
            item
            for item in self.database.list_known_connections(self.character_id)
            if item.id == door.id
        )
        self.assertTrue(persisted.has_lock)
        self.assertFalse(persisted.is_locked)
        confirmation = interaction.followup.send.await_args.args[0]
        self.assertIn("Lockpick succeeded:", confirmation)

    async def test_stealth_tree_rank_improves_lockpicking(self) -> None:
        self.give_tool("lockpicks")
        with self.database._connect() as connection:
            connection.execute(
                "UPDATE characters SET dexterity = 10 WHERE id = ?",
                (self.character_id,),
            )
            connection.execute(
                """
                INSERT INTO character_skills (character_id, skill, rank)
                VALUES (?, 'Stealth', 7)
                """,
                (self.character_id,),
            )
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        door = self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            connection_type=ConnectionType.DOOR,
            has_lock=True,
            is_locked=True,
            unlock_difficulty=8,
        )
        interaction, _ = self.command_interaction()

        await self.cog.lockpick.callback(
            self.cog.lockpick.binding, interaction, "north"
        )

        persisted = next(
            item
            for item in self.database.list_known_connections(self.character_id)
            if item.id == door.id
        )
        self.assertFalse(persisted.is_locked)
        confirmation = interaction.followup.send.await_args.args[0]
        self.assertIn("Lockpick succeeded:", confirmation)
        self.assertIn("Stealth +7", confirmation)

    async def test_failed_lockpick_keeps_door_locked_and_hides_dc(self) -> None:
        self.give_tool("lockpicks")
        with self.database._connect() as connection:
            connection.execute(
                "UPDATE characters SET dexterity = 10 WHERE id = ?",
                (self.character_id,),
            )
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        door = self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            connection_type=ConnectionType.DOOR,
            has_lock=True,
            is_locked=True,
            unlock_difficulty=30,
        )
        interaction, _ = self.command_interaction()

        await self.cog.lockpick.callback(
            self.cog.lockpick.binding, interaction, "north"
        )

        persisted = next(
            item
            for item in self.database.list_known_connections(self.character_id)
            if item.id == door.id
        )
        self.assertTrue(persisted.is_locked)
        embed = interaction.guild.text_channels[0].send.await_args.kwargs["embed"]
        self.assertEqual(
            embed.description,
            "Olof works at the lock, but the mechanism refuses to give. "
            "The lockpicks snap under the strain.",
        )
        confirmation = interaction.followup.send.await_args.args[0]
        self.assertIn("Lockpick failed:", confirmation)
        self.assertIn("Your lockpicks broke.", confirmation)
        self.assertNotIn("DC", confirmation)
        with self.database._connect() as connection:
            durability = connection.execute(
                """
                SELECT durability FROM character_items
                WHERE character_id = ? AND template_id = 'lockpicks'
                """,
                (self.character_id,),
            ).fetchone()["durability"]
        self.assertEqual(durability, 0)

    async def test_lockpick_requires_usable_lockpicks(self) -> None:
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        door = self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            connection_type=ConnectionType.DOOR,
            has_lock=True,
            is_locked=True,
            unlock_difficulty=10,
        )
        interaction, _ = self.command_interaction()

        await self.cog.lockpick.callback(
            self.cog.lockpick.binding, interaction, "north"
        )

        interaction.response.send_message.assert_awaited_once_with(
            "You need usable lockpicks to pick that lock.", ephemeral=True
        )
        persisted = next(
            item
            for item in self.database.list_known_connections(self.character_id)
            if item.id == door.id
        )
        self.assertTrue(persisted.is_locked)

    async def test_failed_disarm_breaks_disarm_kit(self) -> None:
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        trapped = self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            connection_type=ConnectionType.HALLWAY,
            has_trap=True,
            trap_state=TrapState.ARMED,
            trap_detection_difficulty=10,
            trap_disarm_difficulty=30,
            trap_damage_type=TrapDamageType.PHYSICAL,
            trap_damage=3,
        )
        self.database.mark_trap_detected(self.character_id, trapped.id)
        self.give_tool("trap_disarm_kit")
        interaction, _ = self.command_interaction()

        await self.cog.disarm.callback(
            self.cog.disarm.binding, interaction, "north"
        )

        persisted = next(
            item
            for item in self.database.list_known_connections(self.character_id)
            if item.id == trapped.id
        )
        self.assertIs(persisted.trap_state, TrapState.ARMED)
        confirmation = interaction.followup.send.await_args.args[0]
        self.assertIn("Disarm failed:", confirmation)
        self.assertIn("Your Trap Disarm Kit broke.", confirmation)
        with self.database._connect() as connection:
            durability = connection.execute(
                """
                SELECT durability FROM character_items
                WHERE character_id = ? AND template_id = 'trap_disarm_kit'
                """,
                (self.character_id,),
            ).fetchone()["durability"]
        self.assertEqual(durability, 0)

    async def test_disarm_requires_usable_disarm_kit(self) -> None:
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        trapped = self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            connection_type=ConnectionType.HALLWAY,
            has_trap=True,
            trap_state=TrapState.ARMED,
            trap_detection_difficulty=10,
            trap_disarm_difficulty=10,
            trap_damage_type=TrapDamageType.PHYSICAL,
            trap_damage=3,
        )
        self.database.mark_trap_detected(self.character_id, trapped.id)
        interaction, _ = self.command_interaction()

        await self.cog.disarm.callback(
            self.cog.disarm.binding, interaction, "north"
        )

        interaction.response.send_message.assert_awaited_once_with(
            "You need a usable Trap Disarm Kit to disarm that trap.", ephemeral=True
        )

    async def test_door_commands_flavor_already_open_or_closed_state(self) -> None:
        hall = self.cog.world.create_room("hall", "chapel", "Hall")
        self.cog.world.connect_rooms(
            "entrance",
            "north",
            hall.id,
            connection_type=ConnectionType.DOOR,
            is_open=True,
        )
        open_interaction, _ = self.command_interaction()

        await self.cog.door_open.callback(
            self.cog.door_open.binding, open_interaction, "north"
        )

        open_embed = open_interaction.guild.text_channels[0].send.await_args.kwargs[
            "embed"
        ]
        self.assertEqual(
            open_embed.description,
            "Olof tries to open the door, but realizes it's already open."
        )

        self.cog.world.set_connection_open("entrance", "north", is_open=False)
        close_interaction, _ = self.command_interaction()
        await self.cog.door_close.callback(
            self.cog.door_close.binding, close_interaction, "north"
        )

        close_embed = close_interaction.guild.text_channels[0].send.await_args.kwargs[
            "embed"
        ]
        self.assertEqual(
            close_embed.description,
            "Olof tries to close the door, but realizes it's already closed."
        )

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
        character_cog = SimpleNamespace(refresh_dedicated_sheet_for=AsyncMock())
        take_interaction.client = SimpleNamespace(
            get_cog=lambda name: character_cog if name == "CharacterCommands" else None
        )

        await self.cog.take.callback(
            self.cog.take.binding, take_interaction, "health_potion", 1
        )

        public_embed = take_interaction.guild.text_channels[0].send.await_args.kwargs[
            "embed"
        ]
        self.assertEqual(public_embed.author.name, "Olof")
        self.assertEqual(public_embed.description, "Took **1 × Health Potion**.")
        take_interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        take_interaction.followup.send.assert_awaited_once_with(
            "Took **1 × Health Potion**. Posted in #game.", ephemeral=True
        )
        inventory_interaction.edit_original_response.assert_awaited_once()
        refreshed = inventory_interaction.edit_original_response.await_args.kwargs[
            "embeds"
        ][0]
        items = next(
            field.value for field in refreshed.fields if field.name == "Inventory"
        )
        self.assertIn("Health Potion", items)
        character_cog.refresh_dedicated_sheet_for.assert_awaited_once()

    async def test_drop_posts_character_action_in_game(self) -> None:
        self.cog.world.take_loose_item(self.character_id, "copper", 1)
        interaction, _ = self.command_interaction()
        interaction.client = SimpleNamespace(get_cog=lambda _name: None)

        await self.cog.drop.callback(
            self.cog.drop.binding, interaction, "copper", 1
        )

        public_embed = interaction.guild.text_channels[0].send.await_args.kwargs[
            "embed"
        ]
        self.assertEqual(public_embed.author.name, "Olof")
        self.assertEqual(public_embed.description, "Dropped **1 × Copper Coin**.")
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.followup.send.assert_awaited_once_with(
            "Dropped **1 × Copper Coin**. Posted in #game.", ephemeral=True
        )

    async def test_pending_dashboard_refresh_is_applied_to_discord_map(self) -> None:
        self.database.bind_player_view_channel(self.character_id, 88)
        self.database.request_player_map_refresh(self.character_id)
        self.cog.map_messages = SimpleNamespace(refresh=AsyncMock())
        self.cog.bot = SimpleNamespace(
            wait_until_ready=AsyncMock(),
            is_closed=MagicMock(side_effect=(False, True)),
        )

        with patch("rpg_bot.commands.world.asyncio.sleep", new=AsyncMock()):
            await self.cog._process_map_refresh_requests()

        self.cog.map_messages.refresh.assert_awaited_once_with(self.character_id)
        self.assertEqual(self.database.pending_player_map_refreshes(), ())

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
        game_channel = SimpleNamespace(
            name="game", mention="#game", send=AsyncMock()
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=7),
            guild=SimpleNamespace(text_channels=[game_channel]),
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await self.cog.move.callback(
            self.cog.move.binding, interaction, "north"
        )

        self.cog.map_messages.refresh.assert_awaited_once_with(self.character_id)
        movement_embed = game_channel.send.await_args.kwargs["embed"]
        self.assertEqual(movement_embed.author.name, "Olof")
        self.assertIn(
            "**Olof** moves to **Collapsed Hall**.", movement_embed.description
        )
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.followup.send.assert_awaited_once_with(
            "Moved to **Collapsed Hall**. Posted in #game.", ephemeral=True
        )
        self.assertEqual(
            self.cog.world.get_character_room(self.character_id).id,
            destination.id,
        )

    @patch("rpg_bot.commands.world.random.randint")
    async def test_movement_announces_trap_damage_and_refreshes_sheet(
        self, mocked_roll: MagicMock
    ) -> None:
        destination = self.cog.world.create_room("hall", "chapel", "Collapsed Hall")
        self.cog.world.connect_rooms(
            "entrance",
            "north",
            destination.id,
            connection_type=ConnectionType.HALLWAY,
        )
        self.cog.world.set_connection_trap(
            "entrance",
            "north",
            has_trap=True,
            trap_state=TrapState.ARMED,
            trap_detection_difficulty=12,
            trap_damage_type=TrapDamageType.POISON,
            trap_damage=4,
        )
        interaction, _ = self.command_interaction()
        character_cog = SimpleNamespace(refresh_dedicated_sheet_for=AsyncMock())
        interaction.client = SimpleNamespace(
            get_cog=lambda name: character_cog if name == "CharacterCommands" else None
        )

        await self.cog.move.callback(
            self.cog.move.binding, interaction, "north"
        )

        movement_embed = interaction.guild.text_channels[0].send.await_args.kwargs[
            "embed"
        ]
        self.assertIn("A trap triggers!", movement_embed.description)
        self.assertIn("**4 poison damage**", movement_embed.description)
        interaction.followup.send.assert_awaited_once_with(
            "Moved to **Collapsed Hall**. Trap triggered: **4 poison damage**. "
            "HP: **11/15**. Posted in #game.",
            ephemeral=True,
        )
        refreshed_character = (
            character_cog.refresh_dedicated_sheet_for.await_args.args[0]
        )
        self.assertEqual(refreshed_character.hp, 11)
        mocked_roll.assert_not_called()

    @patch("rpg_bot.commands.world.random.randint", return_value=20)
    async def test_search_traps_records_detected_trap(
        self, _mocked_roll: MagicMock
    ) -> None:
        destination = self.cog.world.create_room("hall", "chapel", "Hall")
        trapped = self.cog.world.connect_rooms(
            "entrance",
            "north",
            destination.id,
            connection_type=ConnectionType.HALLWAY,
            has_trap=True,
            trap_state=TrapState.ARMED,
            trap_detection_difficulty=10,
            trap_damage_type=TrapDamageType.PHYSICAL,
            trap_damage=3,
        )
        interaction, _ = self.command_interaction()

        await self.cog.search_traps.callback(
            self.cog.search_traps.binding, interaction
        )

        self.assertTrue(
            self.database.character_knows_trap(self.character_id, trapped.id)
        )
        response = interaction.response.send_message.await_args.args[0]
        self.assertIn("You detect a trap at **north**.", response)

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
