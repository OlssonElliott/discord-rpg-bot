"""Character portrait command and persistence support."""

from __future__ import annotations

import asyncio

import discord

from .management_views import DMPortraitPreviewView, PortraitPreviewView
from ...app.checks import is_dm
from ...characters.models import Character
from ...media.portraits import (
    DEFAULT_DM_PORTRAIT_KEY,
    InvalidPortraitError,
    MAX_PORTRAIT_BYTES,
    default_portrait_key,
    is_default_portrait_key,
)


def restore_default_portrait(
    cog, user_id: int, character: Character
) -> Character:
    key = default_portrait_key(character.race, character.gender)
    updated = cog.database.set_character_portrait(
        user_id, character.character_id, key
    )
    if character.portrait_key != key:
        cog.portrait_store.remove(character.portrait_key)
    return updated


async def dm_portrait(
    cog,
    interaction: discord.Interaction,
    image: discord.Attachment | None,
    remove: bool,
) -> None:
    user_id = interaction.user.id
    stored_key = cog.database.get_dm_portrait(user_id)
    current_key = stored_key if isinstance(stored_key, str) else None

    if remove:
        if image is not None:
            await interaction.response.send_message(
                "Choose either an image to upload or `remove: True`, not both.",
                ephemeral=True,
            )
            return
        if current_key is None:
            await interaction.response.send_message(
                "You are already using the default Dungeon Master portrait.",
                ephemeral=True,
            )
            return
        cog.database.set_dm_portrait(user_id, None)
        cog.portrait_store.remove(current_key)
        await interaction.response.send_message(
            "Restored your default Dungeon Master portrait.", ephemeral=True
        )
        return

    if image is None:
        display_key = current_key or DEFAULT_DM_PORTRAIT_KEY
        portrait_path = cog.portrait_store.path_for(display_key)
        view = DMPortraitPreviewView(cog, user_id, current_key)
        if portrait_path is None:
            await interaction.response.send_message(
                "The stored Dungeon Master portrait is unavailable.",
                view=view,
                ephemeral=True,
            )
            return
        portrait_filename = f"portrait{portrait_path.suffix.lower()}"
        portrait_file = discord.File(portrait_path, filename=portrait_filename)
        embed = discord.Embed(
            title="Dungeon Master portrait",
            description=(
                "Attach a new image to `/character portrait` to replace it."
            ),
            colour=discord.Colour.blurple(),
        )
        embed.set_image(url=f"attachment://{portrait_filename}")
        try:
            await interaction.response.send_message(
                embed=embed,
                file=portrait_file,
                view=view,
                ephemeral=True,
            )
        finally:
            portrait_file.close()
        return

    if image.size > MAX_PORTRAIT_BYTES:
        await interaction.response.send_message(
            "Portraits may be at most 5 MB.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        content = await image.read()
        key = await asyncio.to_thread(cog.portrait_store.save_dm, user_id, content)
        try:
            cog.database.set_dm_portrait(user_id, key)
        except Exception:
            cog.portrait_store.remove(key)
            raise
        if current_key != key:
            cog.portrait_store.remove(current_key)
    except InvalidPortraitError as error:
        await interaction.edit_original_response(content=str(error))
        return
    except (discord.HTTPException, OSError):
        await interaction.edit_original_response(
            content="The portrait could not be downloaded or saved. Please try again."
        )
        return

    portrait_path = cog.portrait_store.path_for(key)
    if portrait_path is None:
        await interaction.edit_original_response(
            content="Updated your Dungeon Master portrait."
        )
        return
    portrait_filename = f"portrait{portrait_path.suffix.lower()}"
    portrait_file = discord.File(portrait_path, filename=portrait_filename)
    embed = discord.Embed(
        title="Dungeon Master portrait",
        description="Portrait updated. It will now appear on your DM rolls.",
        colour=discord.Colour.blurple(),
    )
    embed.set_image(url=f"attachment://{portrait_filename}")
    try:
        await interaction.edit_original_response(
            content=None,
            embed=embed,
            attachments=[portrait_file],
            view=DMPortraitPreviewView(cog, user_id, key),
        )
    finally:
        portrait_file.close()


async def portrait(
    cog,
    interaction: discord.Interaction,
    image: discord.Attachment | None = None,
    remove: bool = False,
    *,
    is_dm_check=is_dm,
) -> None:
    character = cog.database.get_character(interaction.user.id)
    if character is None or character.character_id is None:
        if is_dm_check(interaction):
            await cog._dm_portrait(interaction, image, remove)
            return
        await interaction.response.send_message(
            "You do not have an active character. Use `/character manage` first.",
            ephemeral=True,
        )
        return
    if remove:
        if image is not None:
            await interaction.response.send_message(
                "Choose either an image to upload or `remove: True`, not both.",
                ephemeral=True,
            )
            return
        if not character.portrait_key:
            await interaction.response.send_message(
                f"**{character.name}** does not have a portrait.", ephemeral=True
            )
            return
        if is_default_portrait_key(character.portrait_key):
            await interaction.response.send_message(
                f"**{character.name}** is already using the default portrait.",
                ephemeral=True,
            )
            return
        cog.restore_default_portrait(interaction.user.id, character)
        await interaction.response.send_message(
            f"Restored **{character.name}**'s default portrait.", ephemeral=True
        )
        return
    if image is None:
        if not character.portrait_key:
            await interaction.response.send_message(
                f"**{character.name}** does not have a portrait. "
                "Run `/character portrait` again and attach an image to add one.",
                ephemeral=True,
            )
            return
        view = PortraitPreviewView(
            cog,
            interaction.user.id,
            character.character_id,
            character.name,
            character.portrait_key,
        )
        portrait_path = cog.portrait_store.path_for(character.portrait_key)
        if portrait_path is None:
            await interaction.response.send_message(
                "The stored portrait file is unavailable. You can remove its record below.",
                view=view,
                ephemeral=True,
            )
            return
        portrait_filename = f"portrait{portrait_path.suffix.lower()}"
        portrait_file = discord.File(portrait_path, filename=portrait_filename)
        embed = discord.Embed(
            title=f"{character.name}'s portrait",
            description="Attach a new image to `/character portrait` to replace it.",
            colour=discord.Colour.blurple(),
        )
        embed.set_image(url=f"attachment://{portrait_filename}")
        try:
            await interaction.response.send_message(
                embed=embed,
                file=portrait_file,
                view=view,
                ephemeral=True,
            )
        finally:
            portrait_file.close()
        return
    if image.size > MAX_PORTRAIT_BYTES:
        await interaction.response.send_message(
            "Portraits may be at most 5 MB.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        content = await image.read()
        key = await asyncio.to_thread(
            cog.portrait_store.save, character.character_id, content
        )
        try:
            updated = cog.database.set_character_portrait(
                interaction.user.id, character.character_id, key
            )
        except Exception:
            cog.portrait_store.remove(key)
            raise
        if character.portrait_key and character.portrait_key != key:
            cog.portrait_store.remove(character.portrait_key)
    except InvalidPortraitError as error:
        await interaction.edit_original_response(content=str(error))
        return
    except (discord.HTTPException, OSError):
        await interaction.edit_original_response(
            content="The portrait could not be downloaded or saved. Please try again."
        )
        return

    portrait_path = cog.portrait_store.path_for(updated.portrait_key)
    if portrait_path is None:
        await interaction.edit_original_response(
            content=f"Updated **{updated.name}**'s portrait."
        )
        return
    portrait_filename = f"portrait{portrait_path.suffix.lower()}"
    portrait_file = discord.File(portrait_path, filename=portrait_filename)
    embed = discord.Embed(
        title=f"{updated.name}'s portrait",
        description="Portrait updated. It will now appear on rolls and `/status`.",
        colour=discord.Colour.blurple(),
    )
    embed.set_image(url=f"attachment://{portrait_filename}")
    view = PortraitPreviewView(
        cog,
        interaction.user.id,
        updated.character_id,
        updated.name,
        updated.portrait_key,
    )
    try:
        await interaction.edit_original_response(
            content=None,
            embed=embed,
            attachments=[portrait_file],
            view=view,
        )
    finally:
        portrait_file.close()


async def remove_portrait(
    cog,
    interaction: discord.Interaction,
    *,
    is_dm_check=is_dm,
) -> None:
    character = cog.database.get_character(interaction.user.id)
    if character is None or character.character_id is None:
        if is_dm_check(interaction):
            await cog._dm_portrait(interaction, None, True)
            return
        await interaction.response.send_message(
            "You do not have an active character. Use `/character manage` first.",
            ephemeral=True,
        )
        return
    if not character.portrait_key:
        await interaction.response.send_message(
            f"**{character.name}** does not have a portrait.", ephemeral=True
        )
        return
    if is_default_portrait_key(character.portrait_key):
        await interaction.response.send_message(
            f"**{character.name}** is already using the default portrait.",
            ephemeral=True,
        )
        return
    cog.restore_default_portrait(interaction.user.id, character)
    await interaction.response.send_message(
        f"Restored **{character.name}**'s default portrait.", ephemeral=True
    )
