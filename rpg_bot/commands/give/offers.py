"""Offer preparation, recipient discovery, and give autocompletes."""

from __future__ import annotations

import discord
from discord import app_commands

from ...database import CharacterNotFoundError
from .models import GiveOffer, RoomRecipient


ROLLKEEPER_NAME = "rollkeeper"


def character(cog, user_id: int):
    return cog.database.get_character(user_id)


def owned_item(inventory, instance_id: str | None):
    item = next(
        (
            carried
            for carried in inventory.items
            if carried.instance_id == instance_id
        ),
        None,
    )
    if item is None:
        raise ValueError("You can only give an item from your own inventory.")
    return item


def room_recipients(cog, sender_user_id: int) -> tuple[RoomRecipient, ...]:
    with cog.database._connect() as connection:
        sender_row = connection.execute(
            """
            SELECT id, current_room_id
            FROM characters
            WHERE discord_user_id = ?
              AND is_active = 1
              AND is_archived = 0
            ORDER BY id DESC
            LIMIT 1
            """,
            (sender_user_id,),
        ).fetchone()
        if sender_row is None or not sender_row["current_room_id"]:
            return ()

        rows = connection.execute(
            """
            SELECT id, discord_user_id, name
            FROM characters
            WHERE current_room_id = ?
              AND id <> ?
              AND discord_user_id <> ?
              AND is_archived = 0
            ORDER BY name COLLATE NOCASE, id
            """,
            (
                str(sender_row["current_room_id"]),
                int(sender_row["id"]),
                sender_user_id,
            ),
        ).fetchall()

        return tuple(
            RoomRecipient(
                user_id=int(row["discord_user_id"]),
                character_id=int(row["id"]),
                name=str(row["name"]),
            )
            for row in rows
            if str(row["name"]).strip().casefold() != ROLLKEEPER_NAME
        )


def room_recipient(
    cog,
    sender_user_id: int,
    recipient_character_id: int,
) -> RoomRecipient:
    recipient = next(
        (
            candidate
            for candidate in cog.room_recipients(sender_user_id)
            if candidate.character_id == recipient_character_id
        ),
        None,
    )
    if recipient is None:
        raise ValueError(
            "You can only give items or coins to another character in your room."
        )
    return recipient


async def player_autocomplete(
    cog,
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    try:
        recipients = cog.room_recipients(interaction.user.id)
    except CharacterNotFoundError:
        return []

    query = current.strip().casefold()
    return [
        app_commands.Choice(
            name=recipient.name[:100],
            value=str(recipient.character_id),
        )
        for recipient in recipients
        if recipient.name.strip().casefold() != ROLLKEEPER_NAME
        and (not query or query in recipient.name.casefold())
    ][:25]


async def item_autocomplete(
    cog,
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    try:
        character = cog._character(interaction.user.id)
    except CharacterNotFoundError:
        return []

    if character.character_id is None:
        return []

    inventory = cog.database.get_character_inventory(character.character_id)
    equipped = set(inventory.equipment.values())
    query = current.strip().casefold()
    choices: list[app_commands.Choice[str]] = []

    for item in inventory.items:
        if item.instance_id in equipped:
            continue

        template = cog.catalog.get(item.template_id)
        searchable = f"{template.name} {template.template_id}".casefold()
        if query and query not in searchable:
            continue

        quantity_suffix = (
            f" ×{item.quantity}" if item.quantity > 1 else ""
        )
        choices.append(
            app_commands.Choice(
                name=f"{template.name}{quantity_suffix}"[:100],
                value=item.instance_id,
            )
        )
        if len(choices) == 25:
            break

    return choices


def remove_inventory_quantity(
    cog,
    character_id: int,
    instance_id: str,
    quantity: int,
) -> None:
    if quantity <= 0:
        raise ValueError("Quantity must be at least 1.")

    with cog.database._connect() as connection:
        row = connection.execute(
            """
            SELECT quantity
            FROM character_items
            WHERE character_id = ? AND instance_id = ?
            """,
            (character_id, instance_id),
        ).fetchone()
        if row is None or int(row["quantity"]) < quantity:
            raise ValueError("The item is no longer available in that quantity.")

        remaining = int(row["quantity"]) - quantity
        if remaining == 0:
            connection.execute(
                """
                DELETE FROM character_items
                WHERE character_id = ? AND instance_id = ?
                """,
                (character_id, instance_id),
            )
        else:
            connection.execute(
                """
                UPDATE character_items
                SET quantity = ?
                WHERE character_id = ? AND instance_id = ?
                """,
                (remaining, character_id, instance_id),
            )


def give_item_choices(
    cog,
    sender_user_id: int,
) -> tuple[tuple[str, str], ...]:
    sender = cog._character(sender_user_id)
    if sender.character_id is None:
        return ()

    inventory = cog.database.get_character_inventory(sender.character_id)
    equipped = set(inventory.equipment.values())
    choices: list[tuple[str, str]] = []
    for item in inventory.items:
        if item.instance_id in equipped:
            continue
        template = cog.catalog.get(item.template_id)
        quantity_suffix = f" ×{item.quantity}" if item.quantity > 1 else ""
        choices.append(
            (item.instance_id, f"{template.name}{quantity_suffix}")
        )
    return tuple(choices)


def create_offer(
    cog,
    sender_user_id: int,
    recipient_character_id: int,
    *,
    item_instance_id: str | None = None,
    quantity: int = 1,
    copper: int = 0,
    silver: int = 0,
    gold: int = 0,
) -> GiveOffer:
    sender = cog._character(sender_user_id)
    recipient = cog._room_recipient(
        sender_user_id,
        recipient_character_id,
    )
    giving_coins = any((copper, silver, gold))

    if (item_instance_id is None) == (not giving_coins):
        raise ValueError("Choose either one item or coins to give, not both.")
    if sender.character_id is None:
        raise ValueError("You need an active character.")

    inventory = cog.database.get_character_inventory(sender.character_id)
    if item_instance_id is not None:
        inventory_item = cog._owned_item(inventory, item_instance_id)
        if inventory_item.instance_id in inventory.equipment.values():
            raise ValueError("Unequip that item before giving it away.")
        if inventory_item.quantity < quantity:
            raise ValueError("You do not have that many.")
        return GiveOffer(
            sender_user_id=sender_user_id,
            recipient_user_id=recipient.user_id,
            sender_character_id=sender.character_id,
            recipient_character_id=recipient.character_id,
            item_instance_id=inventory_item.instance_id,
            quantity=quantity,
        )

    if inventory.copper < copper:
        raise ValueError("You do not have enough copper.")
    if inventory.silver < silver:
        raise ValueError("You do not have enough silver.")
    if inventory.gold < gold:
        raise ValueError("You do not have enough gold.")

    return GiveOffer(
        sender_user_id=sender_user_id,
        recipient_user_id=recipient.user_id,
        sender_character_id=sender.character_id,
        recipient_character_id=recipient.character_id,
        copper=copper,
        silver=silver,
        gold=gold,
    )
