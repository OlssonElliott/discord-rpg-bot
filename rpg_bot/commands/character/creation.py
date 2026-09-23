"""Character creation session orchestration."""

from __future__ import annotations

import discord

from ...character_creation import (
    CharacterCreationFlow,
    CharacterCreationValidationError,
    CreationStep,
)
from ...database import CharacterAlreadyExistsError
from .creation_views import creation_view
from .presentation import (
    attribute_prompt,
    bonus_prompt,
    creation_prompt,
)


async def create(cog, interaction: discord.Interaction) -> None:
    user_id = interaction.user.id
    flow = CharacterCreationFlow()
    cog.sessions[user_id] = flow
    await interaction.response.send_message(
        creation_prompt(flow),
        view=creation_view(cog, user_id, flow),
        ephemeral=True,
    )


async def submit_component(
    cog, interaction: discord.Interaction, user_id: int, value: object
) -> None:
    flow = cog.sessions.get(user_id)
    if flow is None or interaction.user.id != user_id:
        await interaction.response.edit_message(
            content="This character creation session is no longer active.",
            view=None,
        )
        return
    try:
        next_step = flow.submit(value)
    except CharacterCreationValidationError as error:
        await interaction.response.edit_message(
            content=f"{error}\n{creation_prompt(flow)}",
            view=creation_view(cog, user_id, flow),
        )
        return

    if next_step is not CreationStep.COMPLETE:
        prompt = (
            attribute_prompt({})
            if next_step is CreationStep.ATTRIBUTES
            else bonus_prompt(flow, {})
            if next_step is CreationStep.BONUS_POINTS
            else creation_prompt(flow)
        )
        await interaction.response.edit_message(
            content=prompt,
            view=creation_view(cog, user_id, flow),
        )
        return

    result = flow.result
    if result is None:
        raise RuntimeError("Completed creation flow has no result.")
    previous = cog.database.get_character(user_id)
    try:
        character = cog.service.persist(user_id, result)
    except CharacterAlreadyExistsError as error:
        cog.sessions.pop(user_id, None)
        await interaction.response.edit_message(content=str(error), view=None)
        return
    cog.sessions.pop(user_id, None)
    await interaction.response.edit_message(
        content=(
            f"Created **{character.name}** with {character.max_hp} HP.\n"
            f"{result.summary}"
        ),
        view=None,
    )
    await cog.active_character_changed(interaction, previous, character)


async def back_component(
    cog, interaction: discord.Interaction, user_id: int
) -> None:
    flow = cog.sessions.get(user_id)
    if flow is None or interaction.user.id != user_id:
        await interaction.response.edit_message(
            content="This character creation session is no longer active.",
            view=None,
        )
        return
    step = flow.go_back()
    prompt = (
        attribute_prompt({})
        if step is CreationStep.ATTRIBUTES
        else bonus_prompt(flow, {})
        if step is CreationStep.BONUS_POINTS
        else creation_prompt(flow)
    )
    await interaction.response.edit_message(
        content=prompt,
        view=creation_view(cog, user_id, flow),
    )


async def cancel(cog, interaction: discord.Interaction) -> None:
    removed = cog.sessions.pop(interaction.user.id, None)
    message = (
        "Character creation cancelled."
        if removed is not None
        else "You do not have an active character creation session."
    )
    await interaction.response.send_message(message, ephemeral=True)
