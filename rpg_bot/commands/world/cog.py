"""Small player-facing command surface for the deterministic world service."""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands
import random

from ...database import CharacterNotFoundError, Database
from ...player_view.adapter import DiscordPlayerViewAdapter
from ...world.dungeon import RoomConnection
from ...characters.models import Character
from ...player_view.service import PlayerViewMessageService, PlayerViewService
from ...media.portraits import CharacterPortraitStore
from ...world import ItemStack, Room
from ...world.service import WorldService
from . import actions as world_action_support
from . import autocomplete as world_autocomplete
from . import doors_and_traps as world_door_trap_support
from . import items as world_item_support
from . import map as world_map_support


def _stack_text(stack: ItemStack) -> str:
    return world_action_support.stack_text(stack)


def room_embed(room: Room) -> discord.Embed:
    return world_action_support.room_embed(room)


class WorldCommands(commands.Cog):
    door = app_commands.Group(name="door", description="Interact with doors.")

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
        self._map_refresh_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        return await world_map_support.cog_load(self)

    def cog_unload(self) -> None:
        return world_map_support.cog_unload(self)

    async def _process_map_refresh_requests(self) -> None:
        return await world_map_support.process_map_refresh_requests(self)

    @staticmethod
    async def _map_refresh_sleep() -> None:
        await asyncio.sleep(0.75)

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

    @staticmethod
    def _roll_d20() -> int:
        return random.randint(1, 20)

    async def _error(self, interaction: discord.Interaction, error: ValueError) -> None:
        await interaction.response.send_message(str(error), ephemeral=True)

    async def _send_character_embed(
        self,
        interaction: discord.Interaction,
        character: Character,
        embed: discord.Embed,
    ) -> None:
        return await world_action_support.send_character_embed(
            self,
            interaction,
            character,
            embed,
        )

    @staticmethod
    def _action_embed(description: str) -> discord.Embed:
        return world_action_support.action_embed(description)

    async def _send_character_action(
        self,
        interaction: discord.Interaction,
        character: Character,
        description: str,
        confirmation: str,
    ) -> None:
        return await world_action_support.send_character_action(
            self,
            interaction,
            character,
            description,
            confirmation,
        )

    async def loose_item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await world_autocomplete.loose_item_autocomplete(
            self,
            interaction,
            current,
        )

    async def inventory_item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await world_autocomplete.inventory_item_autocomplete(
            self,
            interaction,
            current,
        )

    async def move_destination_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await world_autocomplete.move_destination_autocomplete(
            self,
            interaction,
            current,
        )

    def _known_doors_from_room(
        self, character_id: int, room: Room
    ) -> dict[str, tuple[str, RoomConnection]]:
        return world_autocomplete.known_doors_from_room(
            self,
            character_id,
            room,
        )

    def _known_connections_from_room(
        self, character_id: int, room: Room
    ) -> dict[str, tuple[str, RoomConnection]]:
        return world_autocomplete.known_connections_from_room(
            self,
            character_id,
            room,
        )

    async def door_exit_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await world_autocomplete.door_exit_autocomplete(
            self,
            interaction,
            current,
        )

    async def disarm_exit_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await world_autocomplete.disarm_exit_autocomplete(
            self,
            interaction,
            current,
        )

    @app_commands.command(name="room", description="Show your current room.")
    async def room(self, interaction: discord.Interaction) -> None:
        return await world_action_support.show_room(
            self,
            interaction,
        )

    @app_commands.command(name="map", description="Open your private dungeon map.")
    async def map(self, interaction: discord.Interaction) -> None:
        return await world_map_support.show_map(
            self,
            interaction,
        )

    @app_commands.command(name="move", description="Move through an exit.")
    @app_commands.describe(destination="Exit or reachable room")
    @app_commands.autocomplete(destination=move_destination_autocomplete)
    async def move(self, interaction: discord.Interaction, destination: str) -> None:
        return await world_action_support.move(
            self,
            interaction,
            destination,
        )

    async def _set_door_state(
        self,
        interaction: discord.Interaction,
        door_exit: str,
        *,
        is_open: bool,
    ) -> None:
        return await world_door_trap_support.set_door_state(
            self,
            interaction,
            door_exit,
            is_open=is_open,
        )

    @door.command(name="open", description="Open a door without moving through it.")
    @app_commands.describe(door_exit="Door exit")
    @app_commands.rename(door_exit="exit")
    @app_commands.autocomplete(door_exit=door_exit_autocomplete)
    async def door_open(self, interaction: discord.Interaction, door_exit: str) -> None:
        await self._set_door_state(interaction, door_exit, is_open=True)

    @door.command(name="close", description="Close a door without moving through it.")
    @app_commands.describe(door_exit="Door exit")
    @app_commands.rename(door_exit="exit")
    @app_commands.autocomplete(door_exit=door_exit_autocomplete)
    async def door_close(self, interaction: discord.Interaction, door_exit: str) -> None:
        await self._set_door_state(interaction, door_exit, is_open=False)

    @app_commands.command(
        name="lockpick",
        description="Attempt to pick a locked door.",
    )
    @app_commands.describe(door_exit="Locked door exit")
    @app_commands.rename(door_exit="exit")
    @app_commands.autocomplete(door_exit=door_exit_autocomplete)
    async def lockpick(
        self, interaction: discord.Interaction, door_exit: str
    ) -> None:
        return await world_door_trap_support.lockpick(
            self,
            interaction,
            door_exit,
        )

    @app_commands.command(
        name="search_traps",
        description="Search nearby passages for hidden traps.",
    )
    async def search_traps(self, interaction: discord.Interaction) -> None:
        return await world_door_trap_support.search_traps(
            self,
            interaction,
        )

    @app_commands.command(
        name="disarm",
        description="Attempt to disarm an armed trap on a visible exit.",
    )
    @app_commands.describe(trap_exit="Visible trapped exit")
    @app_commands.rename(trap_exit="exit")
    @app_commands.autocomplete(trap_exit=disarm_exit_autocomplete)
    async def disarm(
        self,
        interaction: discord.Interaction,
        trap_exit: str,
    ) -> None:
        return await world_door_trap_support.disarm(
            self,
            interaction,
            trap_exit,
        )

    def _adapter(self, client: discord.Client) -> DiscordPlayerViewAdapter:
        return world_map_support.adapter(
            self,
            client,
        )

    async def _ensure_map_channel(
        self, interaction: discord.Interaction, character: Character
    ):
        return await world_map_support.ensure_map_channel(
            self,
            interaction,
            character,
        )

    async def _refresh_existing_map(self, character_id: int) -> bool:
        return await world_map_support.refresh_existing_map(
            self,
            character_id,
        )

    @app_commands.command(name="take", description="Take a loose item from the room.")
    @app_commands.describe(
        item="Item name or ID",
        quantity="Number to take; leave empty to choose from a stack",
    )
    @app_commands.autocomplete(item=loose_item_autocomplete)
    async def take(
        self, interaction: discord.Interaction, item: str, quantity: int | None = None
    ) -> None:
        return await world_item_support.take(
            self,
            interaction,
            item,
            quantity,
        )

    @app_commands.command(
        name="drop", description="Drop an inventory item in the room."
    )
    @app_commands.describe(
        item="Item name or ID",
        quantity="Number to drop; leave empty to choose from a stack",
    )
    @app_commands.autocomplete(item=inventory_item_autocomplete)
    async def drop(
        self, interaction: discord.Interaction, item: str, quantity: int | None = None
    ) -> None:
        return await world_item_support.drop(
            self,
            interaction,
            item,
            quantity,
        )

    @app_commands.command(name="loot", description="Inspect an accessible container.")
    @app_commands.describe(container="Container name or ID")
    async def loot(self, interaction: discord.Interaction, container: str) -> None:
        return await world_item_support.loot(
            self,
            interaction,
            container,
        )

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
        return await world_item_support.take_from(
            self,
            interaction,
            container,
            item,
            quantity,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorldCommands(bot.database, bot))
