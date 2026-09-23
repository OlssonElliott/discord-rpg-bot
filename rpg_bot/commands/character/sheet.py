"""Character sheet presentation and persistent inventory view helpers."""

from __future__ import annotations

import logging
import re
from types import SimpleNamespace

import discord

from .presentation import character_sheet_embed
from .sheet_views import CharacterSheetView
from ...player_view.adapter import DiscordPlayerViewAdapter, private_map_channel_name
from ...discord_support.channels import (
    private_read_only_overwrites,
    require_message_permissions,
    resolve_guild_channel,
)
from ...characters.models import Character
from ...player_view.service import PlayerViewMessageService, PlayerViewService


LOGGER = logging.getLogger(__name__)


def sheet_presentation(
    cog,
    character: Character,
    *,
    include_inventory_summary: bool = True,
) -> tuple[discord.Embed, discord.File | None]:
    portrait_path = cog.portrait_store.path_for(character.portrait_key)
    embed = character_sheet_embed(character)
    embed.set_author(name=character.name)
    if character.character_id is not None and include_inventory_summary:
        inventory = cog.database.get_character_inventory(character.character_id)
        equipment = []
        for slot in ("main_hand", "off_hand", "clothing", "armor", "container"):
            instance_id = next(
                (
                    equipped_id
                    for equipped_slot, equipped_id in inventory.equipment.items()
                    if equipped_slot.value == slot
                ),
                None,
            )
            item_name = (
                cog.item_catalog.get(inventory.item(instance_id).template_id).name
                if instance_id is not None
                else "Nude"
                if slot == "clothing"
                else "Empty"
            )
            equipment.append(
                f"**{slot.replace('_', ' ').title()}** — {item_name}"
            )
        embed.add_field(
            name="Equipment",
            value="\n".join(equipment),
            inline=False,
        )
        equipped_ids = set(inventory.equipment.values())
        carried = []
        for item in inventory.items:
            if item.instance_id in equipped_ids:
                continue
            try:
                item_name = cog.item_catalog.get(item.template_id).name
            except ValueError:
                item_name = item.template_id
            carried.append(
                item_name
                if item.quantity == 1
                else f"{item.quantity} × {item_name}"
            )
        inventory_text = "\n".join(carried) or "Empty"
        if len(inventory_text) > 1024:
            inventory_text = inventory_text[:1021] + "..."
        embed.add_field(
            name="Inventory",
            value=inventory_text,
            inline=False,
        )
    if portrait_path is None:
        return embed, None
    filename = f"character_sheet_portrait{portrait_path.suffix.lower()}"
    embed.set_thumbnail(url=f"attachment://{filename}")
    return (
        embed,
        discord.File(portrait_path, filename=filename),
    )


def dedicated_sheet_presentation(
    cog,
    character: Character,
) -> tuple[list[discord.Embed], discord.File | None]:
    """Render the permanent channel with sheet and inventory visible at once."""
    from ..inventory import inventory_embed

    sheet, portrait_file = cog._sheet_presentation(
        character,
        include_inventory_summary=False,
    )
    assert character.character_id is not None
    inventory = cog.database.get_character_inventory(character.character_id)
    return [
        sheet,
        inventory_embed(character, inventory, cog.item_catalog),
    ], portrait_file


def dedicated_inventory_view(cog, character: Character):
    """Build the persistent interactive inventory shown on the private HUD."""
    from ..inventory import InventoryView

    assert character.character_id is not None
    inventory = cog.database.get_character_inventory(character.character_id)
    return InventoryView(
        cog.inventory_service,
        character.discord_user_id,
        character.character_id,
        inventory,
        dedicated_cog=cog,
    )


def sheet_channel_name(character: Character) -> str:
    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        character.name.casefold(),
    ).strip("-")
    return f"character-{slug or character.character_id}"[:100]

async def ensure_required_player_channels(cog, guild) -> None:
    """Recreate missing private HUD channels for active guild members."""
    if cog.bot is None:
        return
    for character in cog.database.list_all_characters():
        if (
            character.character_id is None
            or not character.is_active
            or character.is_archived
        ):
            continue
        sheet_state = cog.database.get_character_sheet_view_state(
            character.character_id
        )
        if sheet_state is not None and sheet_state.guild_id != guild.id:
            continue
        member = guild.get_member(character.discord_user_id)
        if member is None and hasattr(guild, "fetch_member"):
            try:
                member = await guild.fetch_member(character.discord_user_id)
            except (discord.NotFound, discord.HTTPException):
                member = None
        if member is None:
            continue
        interaction = SimpleNamespace(
            guild=guild,
            user=member,
            client=cog.bot,
        )
        await cog.active_character_changed(interaction, None, character)


async def active_character_changed(
    cog,
    interaction: discord.Interaction,
    previous: Character | None,
    selected: Character,
) -> None:
    """Retarget the player's private channels to the new active character."""
    if (
        (previous is not None and previous.character_id == selected.character_id)
        or getattr(interaction, "guild", None) is None
    ):
        return
    try:
        sheet_channel = await cog._ensure_dedicated_sheet_channel(
            interaction, selected
        )
        await cog._rename_private_channel(
            sheet_channel, cog._sheet_channel_name(selected)
        )
        await cog._refresh_dedicated_sheet(sheet_channel, selected)
    except (discord.HTTPException, OSError, ValueError):
        LOGGER.exception(
            "Could not refresh the character-sheet channel after switching "
            "from %s to %s",
            previous.character_id if previous is not None else None,
            selected.character_id,
        )

    try:
        map_channel = await cog._ensure_dedicated_map_channel(
            interaction, selected
        )
        await cog._rename_private_channel(
            map_channel,
            private_map_channel_name(selected.name, selected.character_id),
        )
        map_state = cog.database.get_player_view_state(selected.character_id)
        if selected.current_room_id is None:
            await cog._show_unplaced_character_map(
                map_channel, map_state.discord_message_id, selected
            )
        else:
            cog.database.ensure_character_location_knowledge(
                selected.character_id
            )
            views = PlayerViewService(cog.database)
            adapter = DiscordPlayerViewAdapter(
                cog.database, views, interaction.client
            )
            await PlayerViewMessageService(views, adapter).refresh(
                selected.character_id
            )
    except (discord.HTTPException, OSError, ValueError):
        LOGGER.exception(
            "Could not refresh the private map channel after switching from "
            "%s to %s",
            previous.character_id if previous is not None else None,
            selected.character_id,
        )


async def active_character_deactivated(
    cog, interaction: discord.Interaction, character: Character
) -> None:
    """Delete the player's private channels while no character is active."""
    if getattr(interaction, "guild", None) is None:
        return
    sheet_state = cog.database.get_character_sheet_view_state(
        character.character_id
    )
    if sheet_state is not None and sheet_state.guild_id == interaction.guild.id:
        if await cog._delete_private_channel(
            interaction, sheet_state.discord_channel_id
        ):
            cog.database.clear_character_sheet_view_state(
                character.character_id
            )

    map_state = cog.database.get_player_view_state(character.character_id)
    if map_state.discord_channel_id is not None:
        if await cog._delete_private_channel(
            interaction, map_state.discord_channel_id
        ):
            cog.database.clear_player_view_channel(character.character_id)


async def delete_private_channel(
    interaction: discord.Interaction, channel_id: int
) -> bool:
    channel = interaction.guild.get_channel(channel_id)
    if channel is None:
        try:
            fetched = await interaction.client.fetch_channel(channel_id)
            fetched_guild_id = getattr(
                getattr(fetched, "guild", None), "id", None
            )
            if fetched_guild_id != interaction.guild.id:
                return False
            channel = fetched
        except discord.NotFound:
            return True
        except discord.HTTPException:
            LOGGER.exception(
                "Could not resolve private player channel %s", channel_id
            )
            return False
    try:
        await channel.delete(reason="Player unequipped their active character")
        return True
    except discord.HTTPException:
        LOGGER.exception("Could not delete private player channel %s", channel_id)
        return False


async def rename_private_channel(channel, desired_name: str) -> None:
    """Rename a reused HUD channel without blocking its content refresh."""
    if getattr(channel, "name", desired_name) == desired_name:
        return
    if not hasattr(channel, "edit"):
        return
    try:
        await channel.edit(
            name=desired_name,
            reason="Active character changed",
        )
    except discord.HTTPException:
        LOGGER.warning(
            "Could not rename private player channel %s to %s; continuing",
            getattr(channel, "id", "unknown"),
            desired_name,
        )


async def show_unplaced_character_map(
    cog, channel, message_id: int | None, character: Character
) -> None:
    message = None
    if message_id is not None and hasattr(channel, "fetch_message"):
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            message = None
    content = (
        f"**{character.name}** has not been placed in a dungeon room yet. "
        "The map will appear after the DM places the character."
    )
    if message is not None:
        await message.edit(content=content, embeds=[], attachments=[], view=None)
    elif hasattr(channel, "send"):
        message = await channel.send(content)
        cog.database.update_player_view_state(
            character.character_id, discord_message_id=message.id
        )


async def ensure_dedicated_sheet_channel(
    cog, interaction: discord.Interaction, character: Character
):
    assert character.character_id is not None
    guild = interaction.guild
    state = cog.database.get_character_sheet_view_state(character.character_id)
    channel = None
    if state is not None and state.guild_id == guild.id:
        channel = await resolve_guild_channel(
            guild,
            interaction.client,
            state.discord_channel_id,
        )
    if channel is not None:
        require_message_permissions(
            channel,
            getattr(guild, "me", None),
            label="character-sheet",
        )
        return channel

    bot_member = guild.me
    if bot_member is None:
        raise ValueError("I could not resolve my server member permissions.")
    if not bot_member.guild_permissions.manage_channels:
        raise ValueError(
            "I need the **Manage Channels** server permission before I can "
            "create your private character-sheet channel."
        )
    channel = await guild.create_text_channel(
        cog._sheet_channel_name(character),
        overwrites=private_read_only_overwrites(
            guild,
            interaction.user,
            bot_member,
        ),
        reason=f"Private character sheet for character {character.character_id}",
    )
    cog.database.bind_character_sheet_channel(
        character.character_id, guild.id, channel.id
    )
    return channel


async def ensure_dedicated_map_channel(
    cog, interaction: discord.Interaction, character: Character
):
    assert character.character_id is not None
    guild = interaction.guild
    state = cog.database.get_player_view_state(character.character_id)
    channel = None
    if state.discord_channel_id is not None:
        channel = await resolve_guild_channel(
            guild,
            interaction.client,
            state.discord_channel_id,
        )
    if channel is not None:
        require_message_permissions(
            channel,
            getattr(guild, "me", None),
            label="character-sheet",
        )
        return channel

    bot_member = guild.me
    if bot_member is None:
        raise ValueError("I could not resolve my server member permissions.")
    if not bot_member.guild_permissions.manage_channels:
        raise ValueError(
            "I need the **Manage Channels** server permission before I can "
            "create your private map channel."
        )
    channel = await guild.create_text_channel(
        private_map_channel_name(character.name, character.character_id),
        overwrites=private_read_only_overwrites(
            guild,
            interaction.user,
            bot_member,
        ),
        reason=f"Private dungeon HUD for character {character.character_id}",
    )
    PlayerViewService(cog.database).bind_discord_channel(
        character.character_id, channel.id
    )
    return channel


async def edit_dedicated_sheet_message(
    cog, message: discord.Message, character: Character
) -> None:
    embeds, portrait_file = cog._dedicated_sheet_presentation(character)
    try:
        await message.edit(
            embeds=embeds,
            attachments=[portrait_file] if portrait_file is not None else [],
            view=cog._dedicated_inventory_view(character),
        )
    finally:
        if portrait_file is not None:
            portrait_file.close()


async def refresh_dedicated_sheet(
    cog, channel, character: Character
) -> int:
    assert character.character_id is not None
    state = cog.database.get_character_sheet_view_state(character.character_id)
    existing_message = None
    if state is not None and state.discord_message_id is not None:
        try:
            existing_message = await channel.fetch_message(state.discord_message_id)
        except discord.NotFound:
            existing_message = None
    if existing_message is not None:
        await cog._edit_dedicated_sheet_message(existing_message, character)
        return existing_message.id

    embeds, portrait_file = cog._dedicated_sheet_presentation(character)
    try:
        arguments = {
            "embeds": embeds,
            "view": cog._dedicated_inventory_view(character),
        }
        if portrait_file is not None:
            arguments["file"] = portrait_file
        message = await channel.send(**arguments)
    finally:
        if portrait_file is not None:
            portrait_file.close()
    cog.database.set_character_sheet_view_message(
        character.character_id, message.id
    )
    return message.id


async def refresh_dedicated_sheet_for(cog, character: Character) -> bool:
    """Refresh an existing permanent sheet after an inventory mutation."""
    if cog.bot is None or character.character_id is None:
        return False
    state = cog.database.get_character_sheet_view_state(character.character_id)
    if state is None:
        return False
    channel = cog.bot.get_channel(state.discord_channel_id)
    if channel is None:
        try:
            channel = await cog.bot.fetch_channel(state.discord_channel_id)
        except discord.NotFound:
            return False
    await cog._refresh_dedicated_sheet(channel, character)
    return True


async def show_sheet(cog, interaction: discord.Interaction) -> None:
    character = cog.database.get_character(interaction.user.id)
    if character is None or character.character_id is None:
        await interaction.response.send_message(
            "You do not have an active character. Use `/character manage` first.",
            ephemeral=True,
        )
        return
    if getattr(interaction, "guild", None) is not None:
        await interaction.response.defer(ephemeral=True)
        try:
            channel = await cog._ensure_dedicated_sheet_channel(
                interaction, character
            )
            await cog._refresh_dedicated_sheet(channel, character)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except discord.Forbidden as error:
            LOGGER.exception("Discord refused private character-sheet operation")
            await interaction.followup.send(
                "Discord refused the character-sheet operation. The bot needs "
                "**Manage Channels**, **View Channel**, **Send Messages**, "
                "**Embed Links**, and **Attach Files**. "
                f"Discord error code: `{error.code}`.",
                ephemeral=True,
            )
            return
        except (discord.HTTPException, OSError) as error:
            LOGGER.exception("Could not update private character sheet")
            detail = (
                f"HTTP {error.status}, Discord error code `{error.code}`"
                if isinstance(error, discord.HTTPException)
                else "the portrait asset could not be read"
            )
            await interaction.followup.send(
                f"I could not update the private character sheet ({detail}).",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Your private character sheet is ready: {channel.mention}",
            ephemeral=True,
        )
        return
    embed, portrait_file = cog._sheet_presentation(character)
    view = CharacterSheetView(
        cog, interaction.user.id, character.character_id
    )
    try:
        if portrait_file is None:
            await interaction.response.send_message(
                embed=embed, view=view, ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=embed,
                file=portrait_file,
                view=view,
                ephemeral=True,
            )
    finally:
        if portrait_file is not None:
            portrait_file.close()


async def publish_character_sheet(
    cog,
    interaction: discord.Interaction,
    user_id: int,
    character_id: int,
) -> None:
    character = cog.database.get_character_by_id(user_id, character_id)
    if character is None:
        await interaction.response.send_message(
            "That character is no longer available.", ephemeral=True
        )
        return
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        await interaction.response.send_message(
            "This sheet cannot be published in the current channel.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    guild_id = interaction.guild_id or 0
    message_id = cog.database.get_character_sheet_message(
        guild_id, channel.id, character_id
    )
    existing_message = None
    if message_id is not None and hasattr(channel, "fetch_message"):
        try:
            existing_message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            existing_message = None

    action = "Published"
    if existing_message is not None:
        embed, portrait_file = cog._sheet_presentation(character)
        try:
            await existing_message.edit(
                embed=embed,
                attachments=[portrait_file] if portrait_file is not None else [],
            )
            action = "Updated"
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, OSError):
            existing_message = None
        finally:
            if portrait_file is not None:
                portrait_file.close()

    if existing_message is None:
        embed, portrait_file = cog._sheet_presentation(character)
        try:
            if portrait_file is None:
                message = await channel.send(embed=embed)
            else:
                message = await channel.send(embed=embed, file=portrait_file)
        except (discord.Forbidden, discord.HTTPException, OSError):
            await interaction.followup.send(
                "I could not publish the sheet in this channel. Check my permissions.",
                ephemeral=True,
            )
            return
        finally:
            if portrait_file is not None:
                portrait_file.close()
        cog.database.set_character_sheet_message(
            guild_id, channel.id, character_id, message.id
        )

    await interaction.followup.send(
        f"{action} **{character.name}**'s sheet in this channel.",
        ephemeral=True,
    )

