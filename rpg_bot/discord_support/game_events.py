"""Shared Discord presentation for public in-world game events."""

import logging

import discord

from ..models import Character
from ..portraits import CharacterPortraitStore
from .identity import apply_character_identity, portrait_attachment_name


GAME_CHANNEL_NAME = "game"
LOGGER = logging.getLogger(__name__)


async def ensure_game_channel(guild):
    """Ensure the guild has its shared public game-event channel."""
    for channel in getattr(guild, "text_channels", ()):
        if getattr(channel, "name", "").casefold() == GAME_CHANNEL_NAME:
            return channel
    bot_member = getattr(guild, "me", None)
    if (
        bot_member is None
        or not getattr(bot_member.guild_permissions, "manage_channels", False)
    ):
        LOGGER.warning(
            "Could not create #%s in guild %s: Manage Channels is missing",
            GAME_CHANNEL_NAME,
            getattr(guild, "id", "unknown"),
        )
        return None
    try:
        return await guild.create_text_channel(
            GAME_CHANNEL_NAME,
            topic="In-world actions witnessed by other player characters.",
            reason="Public Rollkeeper game-event channel",
        )
    except discord.HTTPException:
        LOGGER.exception(
            "Could not create #%s in guild %s",
            GAME_CHANNEL_NAME,
            getattr(guild, "id", "unknown"),
        )
        return None


async def get_or_create_game_channel(interaction: discord.Interaction):
    """Return the guild's shared public channel for witnessed game events."""
    guild = getattr(interaction, "guild", None)
    if guild is None:
        return None
    return await ensure_game_channel(guild)


async def send_game_event(
    interaction: discord.Interaction,
    character: Character,
    embed: discord.Embed,
    portrait_store: CharacterPortraitStore,
):
    """Post a character-authored event to the guild's shared game log."""
    game_channel = await get_or_create_game_channel(interaction)
    if game_channel is None:
        return None
    portrait_path = apply_character_identity(embed, character, portrait_store)
    if portrait_path is None:
        await game_channel.send(embed=embed)
        return game_channel
    portrait_file = discord.File(
        portrait_path,
        filename=portrait_attachment_name(portrait_path),
    )
    try:
        await game_channel.send(embed=embed, file=portrait_file)
    finally:
        portrait_file.close()
    return game_channel
