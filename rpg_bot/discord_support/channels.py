"""Reusable Discord channel helpers shared by command adapters."""

import discord


async def resolve_guild_channel(guild, client, channel_id: int):
    """Resolve a cached or fetched channel only when it belongs to the guild."""
    channel = guild.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        fetched = await client.fetch_channel(channel_id)
    except discord.NotFound:
        return None
    fetched_guild = getattr(fetched, "guild", None)
    if fetched_guild is guild:
        return fetched
    if getattr(fetched_guild, "id", None) == getattr(guild, "id", None):
        return fetched
    return None


def private_read_only_overwrites(guild, user, bot_member) -> dict:
    """Build the common permission set for private bot-owned player channels."""
    return {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            add_reactions=False,
            create_public_threads=False,
            create_private_threads=False,
            send_messages_in_threads=False,
        ),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
        ),
    }


def require_message_permissions(channel, bot_member, *, label: str) -> None:
    """Validate permissions required to maintain a persistent bot-owned message."""
    if bot_member is None or not hasattr(channel, "permissions_for"):
        return
    permissions = channel.permissions_for(bot_member)
    required = {
        "View Channel": permissions.view_channel,
        "Send Messages": permissions.send_messages,
        "Embed Links": permissions.embed_links,
        "Attach Files": permissions.attach_files,
        "Read Message History": permissions.read_message_history,
    }
    missing = [name for name, enabled in required.items() if not enabled]
    if missing:
        raise ValueError(
            f"I cannot update the existing {label} channel. Missing: "
            + ", ".join(f"**{name}**" for name in missing)
            + "."
        )
