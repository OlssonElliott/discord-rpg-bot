"""Persistence and Discord lifecycle for give requests."""

from __future__ import annotations

import logging

import discord

from .models import GiveOffer
from .views import GiveRequestView


LOGGER = logging.getLogger(__name__)


def create_request(cog, offer: GiveOffer) -> int:
    with cog.database._connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO give_requests (
                sender_user_id, recipient_user_id, sender_character_id,
                recipient_character_id, item_instance_id, quantity,
                copper, silver, gold
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer.sender_user_id, offer.recipient_user_id,
                offer.sender_character_id, offer.recipient_character_id,
                offer.item_instance_id, offer.quantity, offer.copper,
                offer.silver, offer.gold,
            ),
        )
        return int(cursor.lastrowid)


def request_is_pending(cog, request_id: int) -> bool:
    with cog.database._connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM give_requests WHERE id = ? AND status = 'pending'",
            (request_id,),
        ).fetchone()
    return row is not None


def finish_request(cog, request_id: int, status: str) -> None:
    with cog.database._connect() as connection:
        connection.execute(
            "UPDATE give_requests SET status = ? WHERE id = ? AND status = 'pending'",
            (status, request_id),
        )


def set_sender_message(cog, request_id: int, message) -> None:
    with cog.database._connect() as connection:
        connection.execute(
            """UPDATE give_requests SET sender_channel_id = ?, sender_message_id = ?
            WHERE id = ?""",
            (message.channel.id, message.id, request_id),
        )


async def update_sender_request_message(
    cog, client, request_id: int, content: str
) -> None:
    with cog.database._connect() as connection:
        row = connection.execute(
            "SELECT sender_channel_id, sender_message_id FROM give_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
    if row is None or not row["sender_channel_id"] or not row["sender_message_id"]:
        return
    try:
        channel = client.get_channel(int(row["sender_channel_id"]))
        if channel is None:
            channel = await client.fetch_channel(int(row["sender_channel_id"]))
        message = await channel.fetch_message(int(row["sender_message_id"]))
        await message.edit(content=content, view=None)
    except discord.HTTPException:
        LOGGER.debug("Could not update sender give request.", exc_info=True)


async def cancel_request(
    cog, client, sender_user_id: int, request_id: int | None = None
) -> bool:
    with cog.database._connect() as connection:
        if request_id is None:
            row = connection.execute(
                """SELECT id, recipient_channel_id, recipient_message_id,
                sender_channel_id, sender_message_id
                FROM give_requests WHERE sender_user_id = ? AND status = 'pending'
                ORDER BY id DESC LIMIT 1""",
                (sender_user_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """SELECT id, recipient_channel_id, recipient_message_id,
                sender_channel_id, sender_message_id
                FROM give_requests WHERE id = ? AND sender_user_id = ? AND status = 'pending'""",
                (request_id, sender_user_id),
            ).fetchone()
        if row is None:
            return False
        connection.execute(
            "UPDATE give_requests SET status = 'cancelled' WHERE id = ?",
            (row["id"],),
        )

    if row["recipient_channel_id"] and row["recipient_message_id"]:
        try:
            channel = client.get_channel(int(row["recipient_channel_id"]))
            if channel is None:
                channel = await client.fetch_channel(int(row["recipient_channel_id"]))
            message = await channel.fetch_message(int(row["recipient_message_id"]))
            await message.edit(
                content="Transfer request cancelled by sender.",
                view=None,
            )
        except discord.HTTPException:
            LOGGER.debug("Could not update cancelled give request.", exc_info=True)

    await cog.update_sender_request_message(
        client,
        int(row["id"]),
        "Transfer request cancelled.",
    )
    return True


async def send_offer_request(
    cog,
    client,
    offer: GiveOffer,
):
    recipient_user = client.get_user(offer.recipient_user_id)
    if recipient_user is None:
        try:
            recipient_user = await client.fetch_user(offer.recipient_user_id)
        except discord.HTTPException as error:
            raise ValueError(
                "I couldn't find that player's Discord account."
            ) from error

    description = cog.describe_offer(offer)
    request_id = cog.create_request(offer)
    view = GiveRequestView(
        cog,
        offer,
        description=description,
        request_id=request_id,
    )
    try:
        message = await recipient_user.send(
            f"{description}\n\nAccept or decline the transfer below.",
            view=view,
        )
    except discord.HTTPException as error:
        cog.finish_request(request_id, "cancelled")
        raise ValueError(
            f"I couldn't send {recipient_user.mention} the transfer request. "
            "They may have direct messages disabled."
        ) from error

    view.message = message
    with cog.database._connect() as connection:
        connection.execute(
            """UPDATE give_requests
            SET recipient_channel_id = ?, recipient_message_id = ?
            WHERE id = ?""",
            (message.channel.id, message.id, request_id),
        )
    return recipient_user, request_id
