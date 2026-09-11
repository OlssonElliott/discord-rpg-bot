"""Small player-facing command surface for the deterministic world service."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..database import CharacterNotFoundError, Database
from ..discord_player_view import DiscordPlayerViewAdapter, private_map_channel_name
from ..models import Character
from ..player_view_service import PlayerViewMessageService, PlayerViewService
from ..portraits import CharacterPortraitStore
from ..world import InventoryHolder, ItemStack, Room, WorldError
from ..world_service import WorldService
from .inventory import refresh_open_inventory
from .player import apply_character_identity, portrait_attachment_name


LOGGER = logging.getLogger(__name__)


def _stack_text(stack: ItemStack) -> str:
    return f"{stack.quantity} × {stack.item.name}"


def room_embed(room: Room) -> discord.Embed:
    embed = discord.Embed(
        title=room.name,
        description=room.description or "No description.",
        colour=discord.Colour.from_rgb(154, 120, 61),
    )
    embed.add_field(
        name="Exits",
        value=(
            "\n".join(
                f"**{exit.name}** → `{exit.destination_room_id}`"
                for exit in room.exits
            )
            or "None"
        ),
        inline=False,
    )
    embed.add_field(
        name="Loose items",
        value="\n".join(_stack_text(stack) for stack in room.loose_items) or "None",
        inline=True,
    )
    embed.add_field(
        name="Containers",
        value="\n".join(entity.name for entity in room.containers) or "None",
        inline=True,
    )
    people = [character.name for character in room.characters]
    people.extend(entity.name for entity in (*room.npcs, *room.enemies))
    embed.add_field(name="Present", value="\n".join(people) or "Nobody", inline=False)
    return embed


class WorldCommands(commands.Cog):
    def __init__(
        self,
        database: Database,
        bot: commands.Bot | None = None,
        portrait_store: CharacterPortraitStore | None = None,
    ) -> None:
        self.database = database
        self.bot = bot
        self.world = WorldService(database)
        self.player_views = PlayerViewService(database)
        self.portrait_store = portrait_store or CharacterPortraitStore()
        self.map_adapter = (
            DiscordPlayerViewAdapter(database, self.player_views, bot)
            if bot is not None
            else None
        )
        self.map_messages = (
            PlayerViewMessageService(self.player_views, self.map_adapter)
            if self.map_adapter is not None
            else None
        )

    async def cog_load(self) -> None:
        """Restore persistent component callbacks for existing HUD messages."""
        if self.bot is None or self.map_adapter is None:
            return
        for state in self.database.list_player_view_states():
            if state.discord_message_id is None:
                continue
            try:
                view = self.player_views.build_player_map(state.character_id)
            except ValueError:
                continue
            self.bot.add_view(
                self.map_adapter.controls(view), message_id=state.discord_message_id
            )

    def _active_character(self, user_id: int) -> Character:
        character = self.database.get_character(user_id)
        if character is None or character.character_id is None:
            raise CharacterNotFoundError(
                "You need an active character before using world commands."
            )
        return character

    def _active_character_id(self, user_id: int) -> int:
        character = self._active_character(user_id)
        assert character.character_id is not None
        return character.character_id

    async def _error(self, interaction: discord.Interaction, error: ValueError) -> None:
        await interaction.response.send_message(str(error), ephemeral=True)

    async def _send_character_embed(
        self,
        interaction: discord.Interaction,
        character: Character,
        embed: discord.Embed,
    ) -> None:
        portrait_path = apply_character_identity(
            embed, character, self.portrait_store
        )
        if portrait_path is None:
            await interaction.response.send_message(embed=embed)
            return
        portrait_file = discord.File(
            portrait_path,
            filename=portrait_attachment_name(portrait_path),
        )
        try:
            await interaction.response.send_message(
                embed=embed, file=portrait_file
            )
        finally:
            portrait_file.close()

    @staticmethod
    def _action_embed(description: str) -> discord.Embed:
        return discord.Embed(
            description=description,
            colour=discord.Colour.from_rgb(154, 120, 61),
        )

    async def loose_item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Suggest loose items in the active character's current room."""
        try:
            room = self.world.get_character_room(
                self._active_character_id(interaction.user.id)
            )
        except (CharacterNotFoundError, WorldError):
            return []
        if room is None:
            return []

        query = current.casefold().strip()
        return [
            app_commands.Choice(
                name=f"{stack.item.name} ({stack.quantity} here)"[:100],
                value=stack.item.id,
            )
            for stack in room.loose_items
            if not query
            or query in stack.item.name.casefold()
            or query in stack.item.id.casefold()
        ][:25]

    async def move_destination_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Suggest reachable rooms without revealing hidden connections."""
        try:
            character_id = self._active_character_id(interaction.user.id)
            room = self.world.get_character_room(character_id)
        except (CharacterNotFoundError, WorldError):
            return []
        if room is None:
            return []

        reachable_room_ids: set[str] = set()
        for connection in self.database.list_known_connections(character_id):
            if connection.from_room_id == room.id:
                reachable_room_ids.add(connection.to_room_id)
            elif connection.bidirectional and connection.to_room_id == room.id:
                reachable_room_ids.add(connection.from_room_id)

        query = current.casefold().strip()
        choices = []
        for exit in room.exits:
            if exit.destination_room_id not in reachable_room_ids:
                continue
            destination = self.database.get_room(exit.destination_room_id)
            if destination is None:
                continue
            if (
                query
                and query not in exit.name.casefold()
                and query not in destination.name.casefold()
                and query not in destination.id.casefold()
            ):
                continue
            choices.append(
                app_commands.Choice(
                    name=f"{destination.name} — via {exit.name}"[:100],
                    value=exit.name,
                )
            )
        return choices[:25]

    @app_commands.command(name="room", description="Show your current room.")
    async def room(self, interaction: discord.Interaction) -> None:
        try:
            character = self._active_character(interaction.user.id)
            room = self.world.get_character_room(character.character_id)
            if room is None:
                raise WorldError("Your character has not been placed in a room yet.")
        except (CharacterNotFoundError, WorldError) as error:
            await self._error(interaction, error)
            return
        await self._send_character_embed(interaction, character, room_embed(room))

    @app_commands.command(name="map", description="Open your private dungeon map.")
    async def map(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "The private dungeon map can only be opened from a server.",
                ephemeral=True,
            )
            return
        try:
            character = self._active_character(interaction.user.id)
            assert character.character_id is not None
            if self.world.get_character_room(character.character_id) is None:
                raise WorldError("Your character has not been placed in a room yet.")
            await interaction.response.defer(ephemeral=True)
            channel = await self._ensure_map_channel(interaction, character)
            self.database.ensure_character_location_knowledge(
                character.character_id
            )
            adapter = self._adapter(interaction.client)
            message_service = PlayerViewMessageService(self.player_views, adapter)
            await message_service.refresh(character.character_id)
        except (CharacterNotFoundError, WorldError, ValueError) as error:
            if interaction.response.is_done():
                await interaction.followup.send(str(error), ephemeral=True)
            else:
                await interaction.response.send_message(str(error), ephemeral=True)
            return
        except discord.Forbidden as error:
            LOGGER.exception("Discord refused private dungeon map operation")
            await interaction.followup.send(
                "Discord refused the map operation. The bot needs **Manage Channels** "
                "to create the private map channel, plus **View Channel**, **Send "
                "Messages**, **Embed Links**, and **Attach Files** inside it. "
                f"Discord error code: `{error.code}`.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as error:
            LOGGER.exception("Discord API error while updating private dungeon map")
            await interaction.followup.send(
                "Discord rejected the map message even though the command ran. "
                f"HTTP {error.status}, Discord error code `{error.code}`. "
                "Check the bot console for the exact API response.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Your private dungeon map is ready: {channel.mention}", ephemeral=True
        )

    @app_commands.command(name="move", description="Move through an exit.")
    @app_commands.describe(destination="Exit or reachable room")
    @app_commands.autocomplete(destination=move_destination_autocomplete)
    async def move(self, interaction: discord.Interaction, destination: str) -> None:
        try:
            character = self._active_character(interaction.user.id)
            room = self.world.move_character(character.character_id, destination)
        except (CharacterNotFoundError, WorldError) as error:
            await self._error(interaction, error)
            return
        await self._send_character_embed(interaction, character, room_embed(room))
        await self._refresh_existing_map(character.character_id)

    def _adapter(self, client: discord.Client) -> DiscordPlayerViewAdapter:
        if self.map_adapter is not None and self.map_adapter.client is client:
            return self.map_adapter
        return DiscordPlayerViewAdapter(self.database, self.player_views, client)

    async def _ensure_map_channel(
        self, interaction: discord.Interaction, character: Character
    ):
        assert character.character_id is not None
        state = self.database.get_player_view_state(character.character_id)
        channel = None
        if state.discord_channel_id is not None:
            channel = interaction.guild.get_channel(state.discord_channel_id)
            if channel is None:
                try:
                    fetched = await interaction.client.fetch_channel(
                        state.discord_channel_id
                    )
                    if getattr(fetched, "guild", None) == interaction.guild:
                        channel = fetched
                except discord.NotFound:
                    pass
        if channel is not None:
            self._require_map_message_permissions(channel, interaction.guild.me)
            return channel

        bot_member = interaction.guild.me
        if bot_member is None:
            raise ValueError("I could not resolve my server member permissions.")
        guild_permissions = bot_member.guild_permissions
        if not guild_permissions.manage_channels:
            raise ValueError(
                "I need the **Manage Channels** server permission before I can "
                "create your private map channel."
            )
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                add_reactions=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False,
            ),
        }
        if bot_member is not None:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
            )
        channel = await interaction.guild.create_text_channel(
            private_map_channel_name(character.name, character.character_id),
            overwrites=overwrites,
            reason=f"Private dungeon HUD for character {character.character_id}",
        )
        self.player_views.bind_discord_channel(character.character_id, channel.id)
        return channel

    @staticmethod
    def _require_map_message_permissions(channel, bot_member) -> None:
        if bot_member is None or not hasattr(channel, "permissions_for"):
            return
        permissions = channel.permissions_for(bot_member)
        required = {
            "View Channel": permissions.view_channel,
            "Send Messages": permissions.send_messages,
            "Embed Links": permissions.embed_links,
            "Attach Files": permissions.attach_files,
            "Read Message History": permissions.read_message_history,
        }
        missing = [name for name, enabled in required.items() if not enabled]
        if missing:
            raise ValueError(
                "I cannot update the existing private map channel. Missing: "
                + ", ".join(f"**{name}**" for name in missing)
                + "."
            )

    async def _refresh_existing_map(self, character_id: int) -> None:
        if self.map_messages is None:
            return
        state = self.database.get_player_view_state(character_id)
        if state.discord_channel_id is None:
            return
        try:
            await self.map_messages.refresh(character_id)
        except (discord.HTTPException, ValueError):
            LOGGER.exception("Could not refresh dungeon HUD for character %s", character_id)

    @app_commands.command(name="take", description="Take a loose item from the room.")
    @app_commands.describe(item="Item name or ID", quantity="Number to take")
    @app_commands.autocomplete(item=loose_item_autocomplete)
    async def take(
        self, interaction: discord.Interaction, item: str, quantity: int = 1
    ) -> None:
        try:
            character = self._active_character(interaction.user.id)
            assert character.character_id is not None
            moved = self.world.take_loose_item(
                character.character_id, item, quantity
            )
        except (CharacterNotFoundError, WorldError) as error:
            await self._error(interaction, error)
            return
        await self._send_character_embed(
            interaction,
            character,
            self._action_embed(f"Took **{_stack_text(moved)}**."),
        )
        await refresh_open_inventory(interaction.user.id, character.character_id)

    @app_commands.command(
        name="drop", description="Drop an inventory item in the room."
    )
    @app_commands.describe(item="Item name or ID", quantity="Number to drop")
    async def drop(
        self, interaction: discord.Interaction, item: str, quantity: int = 1
    ) -> None:
        try:
            character = self._active_character(interaction.user.id)
            assert character.character_id is not None
            moved = self.world.drop_item(
                character.character_id, item, quantity
            )
        except (CharacterNotFoundError, WorldError) as error:
            await self._error(interaction, error)
            return
        await self._send_character_embed(
            interaction,
            character,
            self._action_embed(f"Dropped **{_stack_text(moved)}**."),
        )
        await refresh_open_inventory(interaction.user.id, character.character_id)

    @app_commands.command(name="loot", description="Inspect an accessible container.")
    @app_commands.describe(container="Container name or ID")
    async def loot(self, interaction: discord.Interaction, container: str) -> None:
        try:
            character = self._active_character(interaction.user.id)
            room = self.world.get_character_room(character.character_id)
            if room is None:
                raise WorldError("Your character has not been placed in a room yet.")
            matches = [
                entity
                for entity in room.containers
                if entity.id == container or entity.name.casefold() == container.casefold()
            ]
            if not matches:
                raise WorldError(f"There is no container named '{container}' here.")
            if len(matches) > 1 and all(entity.id != container for entity in matches):
                raise WorldError("That name is ambiguous; use the container ID.")
            selected = next(
                (entity for entity in matches if entity.id == container), matches[0]
            )
            stacks = self.world.inventory(InventoryHolder.entity(selected.id))
        except (CharacterNotFoundError, WorldError) as error:
            await self._error(interaction, error)
            return
        contents = "\n".join(_stack_text(stack) for stack in stacks) or "Empty"
        embed = self._action_embed(contents)
        embed.title = selected.name
        await self._send_character_embed(interaction, character, embed)

    @app_commands.command(
        name="takefrom", description="Take an item from a container in this room."
    )
    @app_commands.describe(
        container="Container name or ID", item="Item name or ID", quantity="Number to take"
    )
    async def take_from(
        self,
        interaction: discord.Interaction,
        container: str,
        item: str,
        quantity: int = 1,
    ) -> None:
        try:
            character = self._active_character(interaction.user.id)
            assert character.character_id is not None
            moved = self.world.take_from_container(
                character.character_id,
                container,
                item,
                quantity,
            )
        except (CharacterNotFoundError, WorldError) as error:
            await self._error(interaction, error)
            return
        await self._send_character_embed(
            interaction,
            character,
            self._action_embed(f"Took **{_stack_text(moved)}**."),
        )
        await refresh_open_inventory(interaction.user.id, character.character_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorldCommands(bot.database, bot))
