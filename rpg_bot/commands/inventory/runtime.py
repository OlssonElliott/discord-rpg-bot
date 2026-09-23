"""Runtime inventory sessions, rendering, and refresh helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import discord

from ...discord_support.game_events import send_game_event
from ...inventory.service import InventoryService
from ...characters.models import Character
from ...media.portraits import CharacterPortraitStore
from .presentation import (
    _stacked_inventory_items,
    inventory_embed,
    inventory_embeds,
    readable_field_pages,
)
from .views import InventoryView


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class OpenInventory:
    service: InventoryService
    character_id: int
    interaction: discord.Interaction
    message: discord.InteractionMessage
    selected_id: str | None
    page: int
    reading_id: str | None
    reading_page: int


_OPEN_INVENTORIES: dict[int, OpenInventory] = {}


def forget_open_inventory(user_id: int, character_id: int | None = None) -> None:
    session = _OPEN_INVENTORIES.get(user_id)
    if session is not None and (
        character_id is None or session.character_id == character_id
    ):
        _OPEN_INVENTORIES.pop(user_id, None)


async def refresh_open_inventory(user_id: int, character_id: int) -> None:
    """Refresh the user's latest private inventory message, if it is still open."""
    session = _OPEN_INVENTORIES.get(user_id)
    if session is None or session.character_id != character_id:
        return
    character = session.service.database.get_character_by_id(
        user_id, session.character_id
    )
    if character is None:
        forget_open_inventory(user_id)
        return
    inventory = session.service.database.get_character_inventory(session.character_id)
    selected_id = (
        session.selected_id
        if any(item.instance_id == session.selected_id for item in inventory.items)
        else None
    )
    reading_id = (
        session.reading_id
        if any(item.instance_id == session.reading_id for item in inventory.items)
        else None
    )
    stacked_items = _stacked_inventory_items(
        inventory.items, session.service.catalog
    )
    page_count = max(1, (len(stacked_items) + 24) // 25)
    page = min(session.page, page_count - 1)
    view = InventoryView(
        session.service,
        user_id,
        session.character_id,
        inventory,
        selected_id,
        page,
        reading_id,
        session.reading_page if reading_id is not None else 0,
    )
    edit_arguments = {
        "embeds": inventory_embeds(
            character,
            inventory,
            session.service.catalog,
            selected_id,
            reading_id,
            view.reading_page if reading_id is not None else 0,
        ),
        "attachments": [],
        "view": view,
    }
    try:
        await session.interaction.edit_original_response(**edit_arguments)
    except discord.HTTPException as original_error:
        try:
            await session.message.edit(**edit_arguments)
        except discord.HTTPException as fallback_error:
            LOGGER.warning(
                "Could not refresh the open inventory for user %s and character %s "
                "(original edit: %r; message edit: %r)",
                user_id,
                character_id,
                original_error,
                fallback_error,
            )
            forget_open_inventory(user_id)
            return
    session.selected_id = selected_id
    session.page = page
    session.reading_id = reading_id
    session.reading_page = view.reading_page if reading_id is not None else 0


async def refresh_character_sheet(
    interaction: discord.Interaction, character: Character
) -> None:
    client = getattr(interaction, "client", None)
    if client is None or not hasattr(client, "get_cog"):
        return
    character_cog = client.get_cog("CharacterCommands")
    if character_cog is None or not hasattr(
        character_cog, "refresh_dedicated_sheet_for"
    ):
        return
    try:
        await character_cog.refresh_dedicated_sheet_for(character)
    except (discord.HTTPException, OSError, ValueError):
        LOGGER.exception(
            "Could not refresh the permanent character sheet for character %s",
            character.character_id,
        )


async def refresh_inventory_views(
    interaction: discord.Interaction, character: Character
) -> None:
    """Refresh both the open inventory and permanent character channel."""
    assert character.character_id is not None
    await refresh_open_inventory(character.discord_user_id, character.character_id)
    await refresh_character_sheet(interaction, character)


async def _announce_room_action(
    interaction: discord.Interaction,
    character: Character,
    description: str,
) -> None:
    character_cog = interaction.client.get_cog("CharacterCommands")
    portrait_store = getattr(character_cog, "portrait_store", CharacterPortraitStore())
    embed = discord.Embed(
        description=description,
        colour=discord.Colour.from_rgb(154, 120, 61),
    )
    await send_game_event(interaction, character, embed, portrait_store)


async def show_inventory(
    interaction: discord.Interaction,
    service: InventoryService,
    character: Character,
    *,
    selected_id: str | None = None,
    page: int = 0,
    reading_id: str | None = None,
    reading_page: int = 0,
    edit: bool = False,
    dedicated_cog=None,
) -> None:
    inventory = service.database.get_character_inventory(character.character_id)
    embeds = inventory_embeds(
        character,
        inventory,
        service.catalog,
        selected_id,
        reading_id,
        reading_page,
    )
    view = InventoryView(
        service,
        character.discord_user_id,
        character.character_id,
        inventory,
        selected_id,
        page,
        reading_id,
        reading_page,
        dedicated_cog,
    )
    portrait_file = None
    if dedicated_cog is not None:
        sheet, portrait_file = dedicated_cog._sheet_presentation(
            character, include_inventory_summary=False
        )
        embeds.insert(0, sheet)
    if edit:
        try:
            await interaction.response.edit_message(
                embeds=embeds,
                attachments=[portrait_file] if portrait_file is not None else [],
                view=view,
            )
        finally:
            if portrait_file is not None:
                portrait_file.close()
        message = interaction.message
    else:
        await interaction.response.send_message(
            embeds=embeds,
            view=view,
            ephemeral=True,
        )
        message = await interaction.original_response()
    if message is not None and dedicated_cog is None:
        _OPEN_INVENTORIES[character.discord_user_id] = OpenInventory(
            service,
            character.character_id,
            interaction,
            message,
            selected_id,
            page,
            reading_id,
            view.reading_page,
        )
