"""Validation and execution for player-to-player transfers."""

from __future__ import annotations

from .models import GiveOffer


ROLLKEEPER_NAME = "rollkeeper"


def describe_offer(cog, offer: GiveOffer) -> str:
    sender, _ = cog._offer_characters(offer)

    if offer.is_item:
        if sender.character_id is None:
            raise ValueError("The sender has no active character.")
        inventory = cog.database.get_character_inventory(sender.character_id)
        item = cog._owned_item(inventory, offer.item_instance_id)
        template = cog.catalog.get(item.template_id)
        return (
            f"**{sender.name}** wants to give you "
            f"**{offer.quantity}× {template.name}**."
        )

    coins = []
    if offer.gold:
        coins.append(f"{offer.gold} gold")
    if offer.silver:
        coins.append(f"{offer.silver} silver")
    if offer.copper:
        coins.append(f"{offer.copper} copper")
    return f"**{sender.name}** wants to give you **{', '.join(coins)}**."


def legacy_recipient_character(cog, offer: GiveOffer):
    if offer.sender_user_id == offer.recipient_user_id:
        raise ValueError("You cannot give something to yourself.")

    with cog.database._connect() as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM characters
            WHERE discord_user_id = ?
              AND is_archived = 0
            ORDER BY id
            """,
            (offer.recipient_user_id,),
        ).fetchall()

    if len(rows) != 1:
        raise ValueError("The receiving character is no longer available.")

    return cog.database.get_character_by_id(
        offer.recipient_user_id,
        int(rows[0]["id"]),
    )


def offer_characters(cog, offer: GiveOffer):
    sender = (
        cog.database.get_character_by_id(
            offer.sender_user_id,
            offer.sender_character_id,
        )
        if offer.sender_character_id is not None
        else cog._character(offer.sender_user_id)
    )
    if sender is None or sender.character_id is None:
        raise ValueError("The sending character is no longer available.")

    if offer.recipient_character_id is not None:
        recipient = cog.database.get_character_by_id(
            offer.recipient_user_id,
            offer.recipient_character_id,
        )
    else:
        recipient = cog._legacy_recipient_character(offer)

    if recipient is None or recipient.character_id is None:
        raise ValueError("The receiving character is no longer available.")
    if recipient.is_archived:
        raise ValueError("The receiving character is no longer available.")
    if recipient.name.strip().casefold() == ROLLKEEPER_NAME:
        raise ValueError("You cannot give items or coins to Rollkeeper.")
    if sender.discord_user_id == recipient.discord_user_id:
        raise ValueError("You cannot give something to yourself.")
    if (
        not sender.current_room_id
        or not recipient.current_room_id
        or sender.current_room_id != recipient.current_room_id
    ):
        raise ValueError(
            "You can only give items or coins to another character in your room."
        )

    return sender, recipient


def accept_item(
    cog,
    offer: GiveOffer,
    sender,
    recipient,
) -> str:
    if sender.character_id is None or recipient.character_id is None:
        raise ValueError("Both characters must still be available.")

    sender_inventory = cog.database.get_character_inventory(sender.character_id)
    item = cog._owned_item(sender_inventory, offer.item_instance_id)

    if item.instance_id in sender_inventory.equipment.values():
        raise ValueError("The item is equipped and cannot be given.")
    if offer.quantity <= 0:
        raise ValueError("Quantity must be at least 1.")
    if item.quantity < offer.quantity:
        raise ValueError(
            f"{sender.name} no longer has enough of that item."
        )

    template = cog.catalog.get(item.template_id)

    # Grant first so receiver capacity is validated before the sender loses
    # anything. If sender state changes before completion, compensate.
    recipient_instance_id = cog.inventory_service.grant(
        recipient,
        item.template_id,
        offer.quantity,
    )

    try:
        refreshed = cog.database.get_character_inventory(sender.character_id)
        sender_item = cog._owned_item(refreshed, offer.item_instance_id)
        if sender_item.instance_id in refreshed.equipment.values():
            raise ValueError("The item was equipped before the transfer completed.")
        if sender_item.quantity < offer.quantity:
            raise ValueError(
                f"{sender.name} no longer has enough of that item."
            )

        cog._remove_inventory_quantity(
            sender.character_id,
            sender_item.instance_id,
            offer.quantity,
        )
    except Exception:
        cog._remove_inventory_quantity(
            recipient.character_id,
            recipient_instance_id,
            offer.quantity,
        )
        raise

    return (
        f"Accepted. **{sender.name}** gave **{recipient.name}** "
        f"**{offer.quantity}× {template.name}**."
    )


def accept_currency(
    cog,
    offer: GiveOffer,
    sender,
    recipient,
) -> str:
    if sender.character_id is None or recipient.character_id is None:
        raise ValueError("Both characters must still be available.")

    if min(offer.copper, offer.silver, offer.gold) < 0:
        raise ValueError("Coin amounts cannot be negative.")
    if not any((offer.copper, offer.silver, offer.gold)):
        raise ValueError("No coins were offered.")

    sender_inventory = cog.database.get_character_inventory(sender.character_id)
    if sender_inventory.copper < offer.copper:
        raise ValueError(f"{sender.name} no longer has enough copper.")
    if sender_inventory.silver < offer.silver:
        raise ValueError(f"{sender.name} no longer has enough silver.")
    if sender_inventory.gold < offer.gold:
        raise ValueError(f"{sender.name} no longer has enough gold.")

    cog.inventory_service.grant_currency(
        recipient,
        copper=offer.copper,
        silver=offer.silver,
        gold=offer.gold,
    )

    try:
        with cog.database._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE character_wallets
                SET copper = copper - ?,
                    silver = silver - ?,
                    gold = gold - ?
                WHERE character_id = ?
                  AND copper >= ?
                  AND silver >= ?
                  AND gold >= ?
                """,
                (
                    offer.copper,
                    offer.silver,
                    offer.gold,
                    sender.character_id,
                    offer.copper,
                    offer.silver,
                    offer.gold,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"{sender.name}'s coin balance changed before "
                    "the transfer completed."
                )
    except Exception:
        with cog.database._connect() as connection:
            connection.execute(
                """
                UPDATE character_wallets
                SET copper = copper - ?,
                    silver = silver - ?,
                    gold = gold - ?
                WHERE character_id = ?
                """,
                (
                    offer.copper,
                    offer.silver,
                    offer.gold,
                    recipient.character_id,
                ),
            )
        raise

    coins = []
    if offer.gold:
        coins.append(f"{offer.gold} gold")
    if offer.silver:
        coins.append(f"{offer.silver} silver")
    if offer.copper:
        coins.append(f"{offer.copper} copper")

    return (
        f"Accepted. **{sender.name}** gave **{recipient.name}** "
        f"**{', '.join(coins)}**."
    )


def accept_offer(cog, offer: GiveOffer) -> str:
    sender, recipient = cog._offer_characters(offer)
    if offer.is_item:
        return cog._accept_item(offer, sender, recipient)
    return cog._accept_currency(offer, sender, recipient)
