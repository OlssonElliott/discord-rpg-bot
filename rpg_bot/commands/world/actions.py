"""Player-facing world presentation and movement support."""

from __future__ import annotations

import discord

from ...database import CharacterNotFoundError
from ...discord_support.game_events import send_game_event
from ...discord_support.identity import (
    apply_character_identity,
    portrait_attachment_name,
)
from ...characters.models import Character
from ...world import ItemStack, Room, WorldError
from ..inventory import refresh_character_sheet


def stack_text(stack: ItemStack) -> str:
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
        value="\n".join(stack_text(stack) for stack in room.loose_items) or "None",
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


async def send_character_embed(
    cog,
    interaction: discord.Interaction,
    character: Character,
    embed: discord.Embed,
) -> None:
    portrait_path = apply_character_identity(
        embed, character, cog.portrait_store
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


def action_embed(description: str) -> discord.Embed:
    return discord.Embed(
        description=description,
        colour=discord.Colour.from_rgb(154, 120, 61),
    )


async def send_character_action(
    cog,
    interaction: discord.Interaction,
    character: Character,
    description: str,
    confirmation: str,
) -> None:
    await interaction.response.defer(ephemeral=True)
    game_channel = await send_game_event(
        interaction,
        character,
        cog._action_embed(description),
        cog.portrait_store,
    )
    if game_channel is not None:
        confirmation += f" Posted in {game_channel.mention}."
    await interaction.followup.send(confirmation, ephemeral=True)


async def show_room(cog, interaction: discord.Interaction) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        room = cog.world.get_character_room(character.character_id)
        if room is None:
            raise WorldError("Your character has not been placed in a room yet.")
    except (CharacterNotFoundError, WorldError) as error:
        await cog._error(interaction, error)
        return
    await cog._send_character_embed(interaction, character, room_embed(room))


async def move(cog, interaction: discord.Interaction, destination: str) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        result = cog.world.move_character_with_result(
            character.character_id, destination
        )
        room = result.room
    except (CharacterNotFoundError, WorldError, ValueError) as error:
        await cog._error(interaction, error)
        return

    description = f"**{character.name}** moves to **{room.name}**."
    confirmation = f"Moved to **{room.name}**."
    refreshed_character = None
    if result.trap_triggered:
        damage_type = (
            f" {result.trap_damage_type.value}"
            if result.trap_damage_type is not None
            else ""
        )
        trap_notice = (
            f"A trap triggers! **{character.name}** takes "
            f"**{result.trap_damage}{damage_type} damage**."
        )
        description += f"\n\n⚠️ {trap_notice}"
        refreshed_character = cog.database.get_character_by_id(
            character.discord_user_id, character.character_id
        )
        if refreshed_character is not None:
            confirmation += (
                f" Trap triggered: **{result.trap_damage}{damage_type} damage**. "
                f"HP: **{refreshed_character.hp}/{refreshed_character.max_hp}**."
            )
    await cog._send_character_action(
        interaction,
        character,
        description,
        confirmation,
    )
    if refreshed_character is not None:
        await refresh_character_sheet(interaction, refreshed_character)
    if await cog._refresh_existing_map(character.character_id):
        cog.database.clear_player_map_refresh(character.character_id)
