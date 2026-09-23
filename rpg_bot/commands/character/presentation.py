"""Presentation helpers for character creation and management."""

from __future__ import annotations

from collections.abc import Mapping

import discord

from ...character_creation import CharacterCreationFlow, CreationStep
from ...character_creation.rules import ATTRIBUTES, STANDARD_ARRAY, apply_modifiers
from ...characters.models import Character


def creation_prompt(flow: CharacterCreationFlow) -> str:
    """Describe a step while components provide its available answers."""
    return creation_prompt_for_step(flow.current_step)


def creation_prompt_for_step(step: CreationStep) -> str:
    return {
        CreationStep.LINEAGE: "**Lineage** — Choose your lineage below.",
        CreationStep.RACE: "**Race** — Choose a race from your lineage.",
        CreationStep.AGE: "**Age** — Choose your age.",
        CreationStep.GENDER: "**Gender** — Choose your gender.",
        CreationStep.NAME: "**Name** — Use the button below to enter a name.",
        CreationStep.ATTRIBUTES: (
            "**Attributes** — Assign each standard-array value exactly once."
        ),
        CreationStep.BONUS_POINTS: (
            "**Bonus points** — Distribute exactly 2 points with the buttons."
        ),
        CreationStep.SKILLS: "**Skills** — Choose exactly two skill trees.",
        CreationStep.COMPLETE: "Character creation is complete.",
    }[step]


def attribute_prompt(assignments: Mapping[str, int]) -> str:
    links = []
    for value in STANDARD_ARRAY:
        attribute = next(
            (
                attribute
                for attribute, assigned_value in assignments.items()
                if assigned_value == value
            ),
            "Not assigned",
        )
        links.append(f"**{value}** → {attribute}")
    link_text = "\n".join(links)
    return (
        f"{creation_prompt_for_step(CreationStep.ATTRIBUTES)}\n"
        f"{link_text}\n"
        "Select a number button, then link it to an attribute in the dropdown."
    )


def bonus_prompt(flow: CharacterCreationFlow, points: Mapping[str, int]) -> str:
    total = sum(points.values())
    if flow.state.base_attributes and flow.state.race and flow.state.age:
        current_scores = apply_modifiers(
            flow.state.base_attributes,
            points,
            flow.state.race,
            flow.state.age,
        )
    else:
        current_scores = {
            attribute: flow.state.base_attributes.get(attribute, 0)
            for attribute in ATTRIBUTES
        }
    allocation = "\n".join(
        f"• {attribute}: **{current_scores[attribute]}** "
        f"(bonus +{points.get(attribute, 0)})"
        for attribute in ATTRIBUTES
    )
    return (
        f"{creation_prompt_for_step(CreationStep.BONUS_POINTS)}\n"
        f"{allocation}\nRemaining: **{2 - total}**"
    )


def attribute_modifier(score: int) -> int:
    """Return the compact roll modifier shown beside a full attribute score."""
    return (score - 10) // 2


def character_sheet_embed(
    character: Character, portrait_filename: str | None = None
) -> discord.Embed:
    """Build a current character sheet directly from persisted game state."""
    profile = " • ".join(
        value
        for value in (character.race, character.lineage, character.age, character.gender)
        if value
    )
    embed = discord.Embed(
        title=character.name,
        description=profile or "Character sheet",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name="HP", value=f"**{character.hp}/{character.max_hp}**", inline=True)
    embed.add_field(name="Stance", value=character.stance.display_name, inline=True)

    if character.attributes:
        attributes = "\n".join(
            f"**{attribute}** {character.attributes[attribute]} "
            f"({attribute_modifier(character.attributes[attribute]):+d})"
            for attribute in ATTRIBUTES
            if attribute in character.attributes
        )
    else:
        attributes = "No attributes recorded."
    embed.add_field(name="Attributes", value=attributes, inline=False)

    if character.skills:
        skills = "\n".join(
            f"**{skill}** — Rank {rank}"
            for skill, rank in sorted(character.skills.items())
        )
    else:
        skills = "No skills recorded."
    embed.add_field(name="Skills", value=skills, inline=False)
    if portrait_filename is not None:
        embed.set_thumbnail(url=f"attachment://{portrait_filename}")
    return embed


def management_prompt(
    characters: list[Character], selected_id: int | None = None
) -> str:
    lines = ["**Your characters**"]
    for character in characters:
        markers = []
        if character.is_active:
            markers.append("active")
        if character.character_id == selected_id:
            markers.append("selected")
        suffix = f" — {', '.join(markers)}" if markers else ""
        portrait = " 🖼️" if getattr(character, "portrait_key", None) else ""
        lines.append(f"• {character.name}{portrait}{suffix}")
    lines.append("Choose a character, then activate, unequip, or archive it.")
    return "\n".join(lines)
