"""Reusable Discord application-command permission checks."""

from __future__ import annotations

import discord
from discord import app_commands


class DMRoleRequired(app_commands.CheckFailure):
    pass


def is_dm(interaction: discord.Interaction) -> bool:
    """Return whether the interaction user has the configured DM role."""
    role_name = interaction.client.config.dm_role_name
    user = interaction.user
    return isinstance(user, discord.Member) and any(
        role.name == role_name for role in user.roles
    )


def dm_only() -> app_commands.Check:
    async def predicate(interaction: discord.Interaction) -> bool:
        if is_dm(interaction):
            return True
        role_name = interaction.client.config.dm_role_name
        raise DMRoleRequired(f"You need the `{role_name}` role to use this command.")

    return app_commands.check(predicate)
