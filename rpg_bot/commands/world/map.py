"""Private dungeon map lifecycle and Discord HUD support."""

from __future__ import annotations

import asyncio
import logging

import discord

from ...database import CharacterNotFoundError
from ...player_view.adapter import DiscordPlayerViewAdapter, private_map_channel_name
from ...discord_support.channels import (
    private_read_only_overwrites,
    require_message_permissions,
    resolve_guild_channel,
)
from ...characters.models import Character
from ...player_view.service import PlayerViewMessageService
from ...world import WorldError


LOGGER = logging.getLogger(__name__)


async def cog_load(cog) -> None:
    """Restore persistent component callbacks for existing HUD messages."""
    if cog.bot is None or cog.map_adapter is None:
        return
    for state in cog.database.list_player_view_states():
        if state.discord_message_id is None:
            continue
        try:
            view = cog.player_views.build_player_map(state.character_id)
        except ValueError:
            continue
        cog.bot.add_view(
            cog.map_adapter.controls(view), message_id=state.discord_message_id
        )
    cog._map_refresh_task = asyncio.create_task(
        cog._process_map_refresh_requests(),
        name="player-map-refresh-requests",
    )


def cog_unload(cog) -> None:
    if cog._map_refresh_task is not None:
        cog._map_refresh_task.cancel()


async def process_map_refresh_requests(cog) -> None:
    assert cog.bot is not None
    await cog.bot.wait_until_ready()
    while not cog.bot.is_closed():
        for character_id in cog.database.pending_player_map_refreshes():
            # Consume before rendering so a newer mutation that arrives while
            # Discord is being updated leaves a fresh request behind.
            cog.database.clear_player_map_refresh(character_id)
            if not await cog._refresh_existing_map(character_id):
                try:
                    cog.database.request_player_map_refresh(character_id)
                except CharacterNotFoundError:
                    pass
        await cog._map_refresh_sleep()


async def show_map(cog, interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "The private dungeon map can only be opened from a server.",
            ephemeral=True,
        )
        return
    try:
        character = cog._active_character(interaction.user.id)
        assert character.character_id is not None
        if cog.world.get_character_room(character.character_id) is None:
            raise WorldError("Your character has not been placed in a room yet.")
        await interaction.response.defer(ephemeral=True)
        channel = await cog._ensure_map_channel(interaction, character)
        cog.database.ensure_character_location_knowledge(
            character.character_id
        )
        adapter = cog._adapter(interaction.client)
        message_service = PlayerViewMessageService(cog.player_views, adapter)
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


def adapter(cog, client: discord.Client) -> DiscordPlayerViewAdapter:
    if cog.map_adapter is not None and cog.map_adapter.client is client:
        return cog.map_adapter
    return DiscordPlayerViewAdapter(cog.database, cog.player_views, client)


async def ensure_map_channel(
    cog, interaction: discord.Interaction, character: Character
):
    assert character.character_id is not None
    state = cog.database.get_player_view_state(character.character_id)
    channel = None
    if state.discord_channel_id is not None:
        channel = await resolve_guild_channel(
            interaction.guild,
            interaction.client,
            state.discord_channel_id,
        )
    if channel is not None:
        require_message_permissions(
            channel,
            interaction.guild.me,
            label="private map",
        )
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
    channel = await interaction.guild.create_text_channel(
        private_map_channel_name(character.name, character.character_id),
        overwrites=private_read_only_overwrites(
            interaction.guild,
            interaction.user,
            bot_member,
        ),
        reason=f"Private dungeon HUD for character {character.character_id}",
    )
    cog.player_views.bind_discord_channel(character.character_id, channel.id)
    return channel


async def refresh_existing_map(cog, character_id: int) -> bool:
    if cog.map_messages is None:
        return False
    try:
        state = cog.database.get_player_view_state(character_id)
    except CharacterNotFoundError:
        return True
    if state.discord_channel_id is None:
        return True
    try:
        await cog.map_messages.refresh(character_id)
    except (discord.HTTPException, ValueError):
        LOGGER.exception("Could not refresh dungeon HUD for character %s", character_id)
        return False
    return True
