"""Small player-facing command surface for the deterministic world service."""

import discord
from discord import app_commands
from discord.ext import commands

from ..database import CharacterNotFoundError, Database
from ..models import Character
from ..world import InventoryHolder, ItemStack, Room, WorldError
from ..world_service import WorldService
from .inventory import refresh_open_inventory


def _stack_text(stack: ItemStack) -> str:
    return f"{stack.quantity} × {stack.item.name}"


def room_embed(room: Room) -> discord.Embed:
    embed = discord.Embed(
        title=room.name,
        description=room.description or "No description.",
        colour=discord.Colour.blurple(),
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
    def __init__(self, database: Database) -> None:
        self.database = database
        self.world = WorldService(database)

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

    @app_commands.command(name="room", description="Show your current room.")
    async def room(self, interaction: discord.Interaction) -> None:
        try:
            room = self.world.get_character_room(
                self._active_character_id(interaction.user.id)
            )
            if room is None:
                raise WorldError("Your character has not been placed in a room yet.")
        except (CharacterNotFoundError, WorldError) as error:
            await self._error(interaction, error)
            return
        await interaction.response.send_message(embed=room_embed(room))

    @app_commands.command(name="move", description="Move through an exit.")
    @app_commands.describe(destination="Exit name or connected room ID")
    async def move(self, interaction: discord.Interaction, destination: str) -> None:
        try:
            room = self.world.move_character(
                self._active_character_id(interaction.user.id), destination
            )
        except (CharacterNotFoundError, WorldError) as error:
            await self._error(interaction, error)
            return
        await interaction.response.send_message(embed=room_embed(room))

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
        await interaction.response.send_message(
            f"**{character.name}** took {_stack_text(moved)}."
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
        await interaction.response.send_message(
            f"**{character.name}** dropped {_stack_text(moved)}."
        )
        await refresh_open_inventory(interaction.user.id, character.character_id)

    @app_commands.command(name="loot", description="Inspect an accessible container.")
    @app_commands.describe(container="Container name or ID")
    async def loot(self, interaction: discord.Interaction, container: str) -> None:
        try:
            character_id = self._active_character_id(interaction.user.id)
            room = self.world.get_character_room(character_id)
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
        await interaction.response.send_message(f"**{selected.name}**\n{contents}")

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
        await interaction.response.send_message(
            f"**{character.name}** took {_stack_text(moved)}."
        )
        await refresh_open_inventory(interaction.user.id, character.character_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorldCommands(bot.database))
