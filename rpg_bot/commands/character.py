"""Interactive Discord adapter for deterministic character creation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from ..character_creation import (
    CharacterCreationFlow,
    CharacterCreationValidationError,
    CreationStep,
)
from ..character_creation.rules import ATTRIBUTES, STANDARD_ARRAY, apply_modifiers
from ..character_creation.service import CharacterCreationService
from ..checks import is_dm
from ..database import CharacterAlreadyExistsError, CharacterNotFoundError, Database
from ..discord_player_view import DiscordPlayerViewAdapter, private_map_channel_name
from ..models import Character
from ..inventory import DEFAULT_ITEM_CATALOG_PATH, ItemCatalog
from ..inventory_service import InventoryService
from ..portraits import (
    CharacterPortraitStore,
    DEFAULT_DM_PORTRAIT_KEY,
    InvalidPortraitError,
    MAX_PORTRAIT_BYTES,
    default_portrait_key,
    is_default_portrait_key,
)
from ..player_view_service import PlayerViewMessageService, PlayerViewService


LOGGER = logging.getLogger(__name__)


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


class OwnedView(discord.ui.View):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        *,
        timeout: float | None = 15 * 60,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "This character creation session belongs to another player.",
            ephemeral=True,
        )
        return False


class BackButton(discord.ui.Button):
    def __init__(self, owner_view: OwnedView, *, row: int = 1) -> None:
        self.owner_view = owner_view
        super().__init__(
            label="Back",
            style=discord.ButtonStyle.secondary,
            emoji="↩️",
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.owner_view.cog.back_component(
            interaction, self.owner_view.user_id
        )


class ChoiceSelect(discord.ui.Select):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        choices: tuple[str, ...],
        placeholder: str,
    ) -> None:
        self.cog = cog
        self.user_id = user_id
        super().__init__(
            placeholder=placeholder,
            options=[discord.SelectOption(label=choice, value=choice) for choice in choices],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.submit_component(interaction, self.user_id, self.values[0])


class ChoiceView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        choices: tuple[str, ...],
        placeholder: str,
    ) -> None:
        super().__init__(cog, user_id)
        self.add_item(ChoiceSelect(cog, user_id, choices, placeholder))
        if cog.sessions[user_id].current_step is not CreationStep.LINEAGE:
            self.add_item(BackButton(self))


class NameModal(discord.ui.Modal, title="Choose your character name"):
    name = discord.ui.TextInput(
        label="Character name",
        placeholder="Enter a name",
        min_length=1,
        max_length=100,
    )

    def __init__(self, cog: CharacterCommands, user_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.submit_component(interaction, self.user_id, str(self.name))


class NameButton(discord.ui.Button):
    def __init__(self, cog: CharacterCommands, user_id: int) -> None:
        super().__init__(label="Enter name", style=discord.ButtonStyle.primary, emoji="✏️")
        self.cog = cog
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(NameModal(self.cog, self.user_id))


class NameView(OwnedView):
    def __init__(self, cog: CharacterCommands, user_id: int) -> None:
        super().__init__(cog, user_id)
        self.add_item(NameButton(cog, user_id))
        self.add_item(BackButton(self))


class AttributeNumberButton(discord.ui.Button):
    def __init__(
        self,
        attribute_view: AttributeView,
        value: int,
        row: int,
    ) -> None:
        self.attribute_view = attribute_view
        self.value = value
        is_linked = value in attribute_view.assignments.values()
        super().__init__(
            label=str(value),
            style=(
                discord.ButtonStyle.primary
                if value == attribute_view.selected_value
                else discord.ButtonStyle.success
                if is_linked
                else discord.ButtonStyle.secondary
            ),
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = AttributeView(
            self.attribute_view.cog,
            self.attribute_view.user_id,
            self.attribute_view.assignments,
            selected_value=self.value,
        )
        await interaction.response.edit_message(
            content=attribute_prompt(view.assignments), view=view
        )


class AttributeLinkSelect(discord.ui.Select):
    def __init__(self, attribute_view: AttributeView) -> None:
        self.attribute_view = attribute_view
        current_attribute = next(
            (
                attribute
                for attribute, value in attribute_view.assignments.items()
                if value == attribute_view.selected_value
            ),
            None,
        )
        super().__init__(
            placeholder=(
                f"Link {attribute_view.selected_value} to an attribute"
                if attribute_view.selected_value is not None
                else "Choose a number first"
            ),
            options=[
                discord.SelectOption(
                    label=attribute,
                    value=attribute,
                    default=attribute == current_attribute,
                )
                for attribute in ATTRIBUTES
            ],
            disabled=attribute_view.selected_value is None,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_value = self.attribute_view.selected_value
        if selected_value is None:
            return
        chosen_attribute = self.values[0]
        assignments = dict(self.attribute_view.assignments)
        previous_attribute = next(
            (
                attribute
                for attribute, value in assignments.items()
                if value == selected_value
            ),
            None,
        )
        previous_value = assignments.get(chosen_attribute)
        if previous_attribute != chosen_attribute:
            if previous_attribute is not None and previous_value is not None:
                assignments[previous_attribute] = previous_value
            elif previous_attribute is not None:
                assignments.pop(previous_attribute)
            assignments[chosen_attribute] = selected_value
        view = AttributeView(
            self.attribute_view.cog,
            self.attribute_view.user_id,
            assignments,
        )
        await interaction.response.edit_message(
            content=attribute_prompt(assignments), view=view
        )


class ResetAttributesButton(discord.ui.Button):
    def __init__(self, attribute_view: AttributeView) -> None:
        self.attribute_view = attribute_view
        super().__init__(
            label="Reset",
            style=discord.ButtonStyle.secondary,
            disabled=not attribute_view.assignments,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = AttributeView(
            self.attribute_view.cog,
            self.attribute_view.user_id,
        )
        await interaction.response.edit_message(content=attribute_prompt({}), view=view)


class ConfirmAttributesButton(discord.ui.Button):
    def __init__(self, attribute_view: AttributeView) -> None:
        self.attribute_view = attribute_view
        super().__init__(
            label="Confirm attributes",
            style=discord.ButtonStyle.primary,
            disabled=(
                set(attribute_view.assignments) != set(ATTRIBUTES)
                or set(attribute_view.assignments.values()) != set(STANDARD_ARRAY)
            ),
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.attribute_view.cog.submit_component(
            interaction,
            self.attribute_view.user_id,
            self.attribute_view.assignments,
        )


class AttributeView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        assignments: Mapping[str, int] | None = None,
        *,
        selected_value: int | None = None,
    ) -> None:
        super().__init__(cog, user_id)
        self.assignments = dict(assignments or {})
        self.selected_value = selected_value
        for index, value in enumerate(STANDARD_ARRAY):
            self.add_item(AttributeNumberButton(self, value, 0 if index < 5 else 1))
        self.add_item(AttributeLinkSelect(self))
        self.add_item(ResetAttributesButton(self))
        self.add_item(ConfirmAttributesButton(self))
        self.add_item(BackButton(self, row=3))


class BonusButton(discord.ui.Button):
    def __init__(
        self,
        bonus_view: BonusView,
        attribute: str,
        delta: int,
        row: int,
    ) -> None:
        self.bonus_view = bonus_view
        self.attribute = attribute
        self.delta = delta
        current = bonus_view.points.get(attribute, 0)
        total = sum(bonus_view.points.values())
        super().__init__(
            label=f"{'+' if delta > 0 else '−'} {attribute}",
            style=(
                discord.ButtonStyle.success
                if delta > 0
                else discord.ButtonStyle.secondary
            ),
            disabled=(total >= 2 if delta > 0 else current == 0),
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        points = dict(self.bonus_view.points)
        updated = points.get(self.attribute, 0) + self.delta
        if updated:
            points[self.attribute] = updated
        else:
            points.pop(self.attribute, None)
        view = BonusView(
            self.bonus_view.cog,
            self.bonus_view.user_id,
            self.bonus_view.flow,
            points,
        )
        await interaction.response.edit_message(
            content=bonus_prompt(self.bonus_view.flow, points), view=view
        )


class ConfirmBonusButton(discord.ui.Button):
    def __init__(self, bonus_view: BonusView) -> None:
        self.bonus_view = bonus_view
        super().__init__(
            label="Confirm bonus points",
            style=discord.ButtonStyle.primary,
            disabled=sum(bonus_view.points.values()) != 2,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.bonus_view.cog.submit_component(
            interaction,
            self.bonus_view.user_id,
            self.bonus_view.points,
        )


class BonusView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        flow: CharacterCreationFlow,
        points: Mapping[str, int] | None = None,
    ) -> None:
        super().__init__(cog, user_id)
        self.flow = flow
        self.points = dict(points or {})
        for index, attribute in enumerate(ATTRIBUTES):
            row = index // 2
            self.add_item(BonusButton(self, attribute, 1, row))
            self.add_item(BonusButton(self, attribute, -1, row))
        self.add_item(ConfirmBonusButton(self))
        self.add_item(BackButton(self, row=3))


class SkillSelect(discord.ui.Select):
    def __init__(
        self, cog: CharacterCommands, user_id: int, choices: tuple[str, ...]
    ) -> None:
        self.cog = cog
        self.user_id = user_id
        super().__init__(
            placeholder="Choose two skill trees",
            min_values=2,
            max_values=2,
            options=[discord.SelectOption(label=choice, value=choice) for choice in choices],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.submit_component(interaction, self.user_id, tuple(self.values))


class SkillView(OwnedView):
    def __init__(
        self, cog: CharacterCommands, user_id: int, choices: tuple[str, ...]
    ) -> None:
        super().__init__(cog, user_id)
        self.add_item(SkillSelect(cog, user_id, choices))
        self.add_item(BackButton(self))


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


class CharacterSelect(discord.ui.Select):
    def __init__(
        self,
        manage_view: CharacterManageView,
        characters: list[Character],
    ) -> None:
        self.manage_view = manage_view
        super().__init__(
            custom_id=manage_view.component_id("select"),
            placeholder="Choose a character",
            options=[
                discord.SelectOption(
                    label=character.name,
                    value=str(character.character_id),
                    description="Currently active" if character.is_active else None,
                    default=character.character_id == manage_view.selected_id,
                )
                for character in characters[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_id = int(self.values[0])
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            selected_id,
        )
        await interaction.response.edit_message(
            content=management_prompt(characters, selected_id), view=view
        )


class ActivateCharacterButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        selected = next(
            (
                character
                for character in manage_view.characters
                if character.character_id == manage_view.selected_id
            ),
            None,
        )
        super().__init__(
            custom_id=manage_view.component_id("activate"),
            label="Use character",
            style=discord.ButtonStyle.primary,
            disabled=selected is None or selected.is_active,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_id = self.manage_view.selected_id
        if selected_id is None:
            return
        await interaction.response.defer()
        try:
            previous = self.manage_view.cog.database.get_character(
                self.manage_view.user_id
            )
            selected = self.manage_view.cog.database.select_character(
                self.manage_view.user_id, selected_id
            )
        except CharacterNotFoundError as error:
            await interaction.edit_original_response(content=str(error), view=None)
            return
        await self.manage_view.cog.active_character_changed(
            interaction, previous, selected
        )
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            selected_id,
        )
        await interaction.edit_original_response(
            content=management_prompt(characters, selected_id), view=view
        )


class UnequipCharacterButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        super().__init__(
            custom_id=manage_view.component_id("unequip"),
            label="Unequip active",
            style=discord.ButtonStyle.secondary,
            disabled=not any(
                character.is_active for character in manage_view.characters
            ),
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        active = next(
            (
                character
                for character in self.manage_view.characters
                if character.is_active
            ),
            None,
        )
        self.manage_view.cog.database.deactivate_character(
            self.manage_view.user_id
        )
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            self.manage_view.selected_id,
        )
        await interaction.response.edit_message(
            content=(
                "No character is currently active.\n"
                f"{management_prompt(characters, self.manage_view.selected_id)}"
            ),
            view=view,
        )
        if active is not None:
            await self.manage_view.cog.active_character_deactivated(
                interaction, active
            )


class ArchiveCharacterButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        super().__init__(
            custom_id=manage_view.component_id("archive"),
            label="Remove from Discord",
            style=discord.ButtonStyle.danger,
            disabled=manage_view.selected_id is None,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_id = self.manage_view.selected_id
        if selected_id is None:
            return
        selected = next(
            character
            for character in self.manage_view.characters
            if character.character_id == selected_id
        )
        await interaction.response.edit_message(
            content=(
                f"Remove **{selected.name}** from your selectable characters?\n"
                "Its database record will be kept."
            ),
            view=ArchiveConfirmationView(self.manage_view, selected),
        )


class RemovePortraitButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        selected = next(
            (
                character
                for character in manage_view.characters
                if character.character_id == manage_view.selected_id
            ),
            None,
        )
        super().__init__(
            custom_id=manage_view.component_id("remove-portrait"),
            label="Remove portrait",
            style=discord.ButtonStyle.secondary,
            disabled=(
                selected is None
                or not getattr(selected, "portrait_key", None)
                or is_default_portrait_key(getattr(selected, "portrait_key", None))
            ),
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = next(
            (
                character
                for character in self.manage_view.characters
                if character.character_id == self.manage_view.selected_id
            ),
            None,
        )
        if selected is None or not selected.portrait_key:
            return
        updated = self.manage_view.cog.restore_default_portrait(
            self.manage_view.user_id, selected
        )
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            updated.character_id,
        )
        await interaction.response.edit_message(
            content=(
                f"Restored **{updated.name}**'s default portrait.\n"
                f"{management_prompt(characters, updated.character_id)}"
            ),
            view=view,
        )


class PortraitPreviewView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        character_id: int,
        character_name: str,
        portrait_key: str,
    ) -> None:
        super().__init__(cog, user_id)
        self.character_id = character_id
        self.character_name = character_name
        self.portrait_key = portrait_key
        if is_default_portrait_key(portrait_key):
            self.remove.disabled = True
            self.remove.label = "Using default portrait"

    @discord.ui.button(
        label="Remove portrait",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def remove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        try:
            character = self.cog.database.get_character_by_id(
                self.user_id, self.character_id
            )
            if character is None:
                raise CharacterNotFoundError("That character is not selectable.")
            self.cog.restore_default_portrait(self.user_id, character)
        except CharacterNotFoundError as error:
            await interaction.response.edit_message(
                content=str(error), embed=None, attachments=[], view=None
            )
            return
        self.cog.portrait_store.remove(self.portrait_key)
        await interaction.response.edit_message(
            content=f"Restored **{self.character_name}**'s default portrait.",
            embed=None,
            attachments=[],
            view=None,
        )


class DMPortraitPreviewView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        portrait_key: str | None,
    ) -> None:
        super().__init__(cog, user_id)
        self.portrait_key = portrait_key
        if portrait_key is None:
            self.remove.disabled = True
            self.remove.label = "Using default portrait"

    @discord.ui.button(
        label="Remove portrait",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def remove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        self.cog.database.set_dm_portrait(self.user_id, None)
        self.cog.portrait_store.remove(self.portrait_key)
        await interaction.response.edit_message(
            content="Restored your default Dungeon Master portrait.",
            embed=None,
            attachments=[],
            view=None,
        )


class ConfirmArchiveButton(discord.ui.Button):
    def __init__(
        self, manage_view: CharacterManageView, character: Character
    ) -> None:
        self.manage_view = manage_view
        self.character = character
        super().__init__(label="Confirm removal", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            archived = self.manage_view.cog.database.archive_character(
                self.manage_view.user_id, self.character.character_id
            )
        except CharacterNotFoundError as error:
            await interaction.response.edit_message(content=str(error), view=None)
            return
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        if not characters:
            await interaction.response.edit_message(
                content=f"Archived **{archived.name}**. You have no selectable characters.",
                view=None,
            )
            if self.character.is_active:
                await self.manage_view.cog.active_character_deactivated(
                    interaction, self.character
                )
            return
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
        )
        await interaction.response.edit_message(
            content=(
                f"Archived **{archived.name}**.\n"
                f"{management_prompt(characters)}"
            ),
            view=view,
        )
        if self.character.is_active:
            replacement = self.manage_view.cog.database.get_character(
                self.manage_view.user_id
            )
            if replacement is not None:
                await self.manage_view.cog.active_character_changed(
                    interaction, self.character, replacement
                )


class CancelArchiveButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            self.manage_view.selected_id,
        )
        await interaction.response.edit_message(
            content=management_prompt(characters, self.manage_view.selected_id),
            view=view,
        )


class ArchiveConfirmationView(OwnedView):
    def __init__(
        self, manage_view: CharacterManageView, character: Character
    ) -> None:
        super().__init__(manage_view.cog, manage_view.user_id)
        self.add_item(ConfirmArchiveButton(manage_view, character))
        self.add_item(CancelArchiveButton(manage_view))


class CharacterManageView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        characters: list[Character],
        selected_id: int | None = None,
    ) -> None:
        super().__init__(cog, user_id, timeout=None)
        self.characters = characters
        self.selected_id = selected_id
        self.add_item(DynamicCharacterManageItem(CharacterSelect(self, characters)))
        self.add_item(DynamicCharacterManageItem(ActivateCharacterButton(self)))
        self.add_item(DynamicCharacterManageItem(UnequipCharacterButton(self)))
        self.add_item(DynamicCharacterManageItem(ArchiveCharacterButton(self)))
        self.add_item(DynamicCharacterManageItem(RemovePortraitButton(self)))

    def component_id(self, action: str) -> str:
        selected = self.selected_id if self.selected_id is not None else "none"
        return f"character-manage:{action}:{self.user_id}:{selected}"


class DynamicCharacterManageItem(
    discord.ui.DynamicItem[discord.ui.Item],
    template=(
        r"character-manage:(?P<action>select|activate|unequip|archive|remove-portrait):"
        r"(?P<user_id>\d+):(?P<selected_id>none|\d+)"
    ),
):
    """Rebuild a manage callback from its ID after a process restart."""

    def __init__(self, item: discord.ui.Item, user_id: int | None = None) -> None:
        super().__init__(item)
        if user_id is None:
            match = self.template.fullmatch(self.custom_id)
            if match is None:
                raise ValueError("Invalid character management component ID.")
            user_id = int(match.group("user_id"))
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item,
        match: re.Match[str],
    ) -> DynamicCharacterManageItem:
        cog = interaction.client.get_cog("CharacterCommands")
        if not isinstance(cog, CharacterCommands):
            raise RuntimeError("Character commands are not loaded.")
        user_id = int(match.group("user_id"))
        selected_value = match.group("selected_id")
        selected_id = None if selected_value == "none" else int(selected_value)
        characters = cog.database.list_characters(user_id)
        manage_view = CharacterManageView(cog, user_id, characters, selected_id)
        rebuilt = next(
            child.item
            for child in manage_view.children
            if isinstance(child, DynamicCharacterManageItem)
            and child.custom_id == item.custom_id
        )
        return cls(rebuilt, user_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "This character management panel belongs to another player.",
            ephemeral=True,
        )
        return False


def creation_view(
    cog: CharacterCommands, user_id: int, flow: CharacterCreationFlow
) -> discord.ui.View:
    step = flow.current_step
    if step in {
        CreationStep.LINEAGE,
        CreationStep.RACE,
        CreationStep.AGE,
        CreationStep.GENDER,
    }:
        return ChoiceView(cog, user_id, flow.valid_choices(), f"Choose {step.value}")
    if step is CreationStep.NAME:
        return NameView(cog, user_id)
    if step is CreationStep.ATTRIBUTES:
        return AttributeView(cog, user_id)
    if step is CreationStep.BONUS_POINTS:
        return BonusView(cog, user_id, flow)
    if step is CreationStep.SKILLS:
        return SkillView(cog, user_id, flow.valid_choices())
    raise ValueError(f"No component view for {step.value}.")


class CharacterSheetView(discord.ui.View):
    def __init__(
        self, cog: CharacterCommands, user_id: int, character_id: int
    ) -> None:
        super().__init__(timeout=15 * 60)
        self.cog = cog
        self.user_id = user_id
        self.character_id = character_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only the character's player can publish this sheet.", ephemeral=True
        )
        return False

    @discord.ui.button(
        label="Inventory",
        style=discord.ButtonStyle.secondary,
        emoji="🎒",
    )
    async def inventory(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        from .inventory import show_inventory

        character = self.cog.database.get_character_by_id(
            self.user_id, self.character_id
        )
        if character is None:
            await interaction.response.send_message(
                "That character is no longer available.", ephemeral=True
            )
            return
        await show_inventory(
            interaction,
            self.cog.inventory_service,
            character,
            edit=True,
        )

    @discord.ui.button(
        label="Publish here",
        style=discord.ButtonStyle.primary,
        emoji="📋",
    )
    async def publish_here(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        await self.cog.publish_character_sheet(
            interaction, self.user_id, self.character_id
        )


class DedicatedCharacterSheetView(discord.ui.View):
    """Persistent controls attached to the private character-sheet channel."""

    def __init__(
        self, cog: CharacterCommands, user_id: int, character_id: int
    ) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
        self.character_id = character_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "This character sheet belongs to another player.", ephemeral=True
        )
        return False

    @discord.ui.button(
        label="Manage inventory",
        style=discord.ButtonStyle.secondary,
        emoji="🎒",
        custom_id="character-sheet:inventory",
    )
    async def inventory(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        from .inventory import show_inventory

        character = self.cog.database.get_character_by_id(
            self.user_id, self.character_id
        )
        if character is None:
            await interaction.response.send_message(
                "That character is no longer available.", ephemeral=True
            )
            return
        await show_inventory(
            interaction, self.cog.inventory_service, character, edit=False
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.primary,
        emoji="🔄",
        custom_id="character-sheet:refresh",
    )
    async def refresh(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        character = self.cog.database.get_character_by_id(
            self.user_id, self.character_id
        )
        if character is None:
            await interaction.response.send_message(
                "That character is no longer available.", ephemeral=True
            )
            return
        await interaction.response.defer()
        if interaction.message is not None:
            await self.cog._edit_dedicated_sheet_message(
                interaction.message, character
            )


class CharacterCommands(commands.GroupCog, group_name="character"):
    """Tracks transient flows per Discord user; only results are persisted."""

    def __init__(
        self,
        database: Database,
        portrait_store: CharacterPortraitStore | None = None,
        bot: commands.Bot | None = None,
    ) -> None:
        self.database = database
        self.bot = bot
        self.portrait_store = portrait_store or CharacterPortraitStore()
        self.service = CharacterCreationService(database)
        self.item_catalog = ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)
        self.inventory_service = InventoryService(database, self.item_catalog)
        self.sessions: dict[int, CharacterCreationFlow] = {}

    async def cog_load(self) -> None:
        if self.bot is None:
            return
        self.bot.add_dynamic_items(DynamicCharacterManageItem)
        all_characters = self.database.list_all_characters()
        characters = {
            character.character_id: character
            for character in all_characters
        }
        for state in self.database.list_character_sheet_view_states():
            character = characters.get(state.character_id)
            if character is None or state.discord_message_id is None:
                continue
            self.bot.add_view(
                DedicatedCharacterSheetView(
                    self,
                    character.discord_user_id,
                    state.character_id,
                ),
                message_id=state.discord_message_id,
            )


    async def active_character_changed(
        self,
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
            sheet_channel = await self._ensure_dedicated_sheet_channel(
                interaction, selected
            )
            await self._rename_private_channel(
                sheet_channel, self._sheet_channel_name(selected)
            )
            await self._refresh_dedicated_sheet(sheet_channel, selected)
        except (discord.HTTPException, OSError, ValueError):
            LOGGER.exception(
                "Could not refresh the character-sheet channel after switching "
                "from %s to %s",
                previous.character_id if previous is not None else None,
                selected.character_id,
            )

        try:
            map_channel = await self._ensure_dedicated_map_channel(
                interaction, selected
            )
            await self._rename_private_channel(
                map_channel,
                private_map_channel_name(selected.name, selected.character_id),
            )
            map_state = self.database.get_player_view_state(selected.character_id)
            if selected.current_room_id is None:
                await self._show_unplaced_character_map(
                    map_channel, map_state.discord_message_id, selected
                )
            else:
                self.database.ensure_character_location_knowledge(
                    selected.character_id
                )
                views = PlayerViewService(self.database)
                adapter = DiscordPlayerViewAdapter(
                    self.database, views, interaction.client
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
        self, interaction: discord.Interaction, character: Character
    ) -> None:
        """Delete the player's private channels while no character is active."""
        if getattr(interaction, "guild", None) is None:
            return
        sheet_state = self.database.get_character_sheet_view_state(
            character.character_id
        )
        if sheet_state is not None and sheet_state.guild_id == interaction.guild.id:
            if await self._delete_private_channel(
                interaction, sheet_state.discord_channel_id
            ):
                self.database.clear_character_sheet_view_state(
                    character.character_id
                )

        map_state = self.database.get_player_view_state(character.character_id)
        if map_state.discord_channel_id is not None:
            if await self._delete_private_channel(
                interaction, map_state.discord_channel_id
            ):
                self.database.clear_player_view_channel(character.character_id)

    @staticmethod
    async def _delete_private_channel(
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

    @staticmethod
    async def _rename_private_channel(channel, desired_name: str) -> None:
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

    async def _show_unplaced_character_map(
        self, channel, message_id: int | None, character: Character
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
            self.database.update_player_view_state(
                character.character_id, discord_message_id=message.id
            )

    def _sheet_presentation(
        self, character: Character, *, include_inventory_summary: bool = True
    ) -> tuple[discord.Embed, discord.File | None]:
        portrait_path = self.portrait_store.path_for(character.portrait_key)
        embed = character_sheet_embed(character)
        embed.set_author(name=character.name)
        if character.character_id is not None and include_inventory_summary:
            inventory = self.database.get_character_inventory(character.character_id)
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
                    self.item_catalog.get(inventory.item(instance_id).template_id).name
                    if instance_id is not None
                    else "Nude"
                    if slot == "clothing"
                    else "Empty"
                )
                equipment.append(
                    f"**{slot.replace('_', ' ').title()}** — {item_name}"
                )
            embed.add_field(
                name="Equipment", value="\n".join(equipment), inline=False
            )
            equipped_ids = set(inventory.equipment.values())
            carried = []
            for item in inventory.items:
                if item.instance_id in equipped_ids:
                    continue
                try:
                    item_name = self.item_catalog.get(item.template_id).name
                except ValueError:
                    item_name = item.template_id
                carried.append(
                    item_name if item.quantity == 1 else f"{item.quantity} × {item_name}"
                )
            inventory_text = "\n".join(carried) or "Empty"
            if len(inventory_text) > 1024:
                inventory_text = inventory_text[:1021] + "..."
            embed.add_field(name="Inventory", value=inventory_text, inline=False)
        if portrait_path is None:
            return embed, None
        filename = f"character_sheet_portrait{portrait_path.suffix.lower()}"
        embed.set_thumbnail(url=f"attachment://{filename}")
        return (
            embed,
            discord.File(portrait_path, filename=filename),
        )

    def _dedicated_sheet_presentation(
        self, character: Character
    ) -> tuple[list[discord.Embed], discord.File | None]:
        """Render the permanent channel with sheet and inventory visible at once."""
        from .inventory import inventory_embed

        sheet, portrait_file = self._sheet_presentation(
            character, include_inventory_summary=False
        )
        assert character.character_id is not None
        inventory = self.database.get_character_inventory(character.character_id)
        return [
            sheet,
            inventory_embed(character, inventory, self.item_catalog),
        ], portrait_file

    @staticmethod
    def _sheet_channel_name(character: Character) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", character.name.casefold()).strip("-")
        return f"character-{slug or character.character_id}"[:100]

    async def _ensure_dedicated_sheet_channel(
        self, interaction: discord.Interaction, character: Character
    ):
        assert character.character_id is not None
        guild = interaction.guild
        state = self.database.get_character_sheet_view_state(character.character_id)
        channel = None
        if state is not None and state.guild_id == guild.id:
            channel = guild.get_channel(state.discord_channel_id)
            if channel is None:
                try:
                    fetched = await interaction.client.fetch_channel(
                        state.discord_channel_id
                    )
                    if getattr(getattr(fetched, "guild", None), "id", None) == guild.id:
                        channel = fetched
                except discord.NotFound:
                    pass
        if channel is not None:
            self._require_sheet_message_permissions(
                channel, getattr(guild, "me", None)
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
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
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
        channel = await guild.create_text_channel(
            self._sheet_channel_name(character),
            overwrites=overwrites,
            reason=f"Private character sheet for character {character.character_id}",
        )
        self.database.bind_character_sheet_channel(
            character.character_id, guild.id, channel.id
        )
        return channel

    async def _ensure_dedicated_map_channel(
        self, interaction: discord.Interaction, character: Character
    ):
        assert character.character_id is not None
        guild = interaction.guild
        state = self.database.get_player_view_state(character.character_id)
        channel = None
        if state.discord_channel_id is not None:
            channel = guild.get_channel(state.discord_channel_id)
            if channel is None:
                try:
                    fetched = await interaction.client.fetch_channel(
                        state.discord_channel_id
                    )
                    if getattr(getattr(fetched, "guild", None), "id", None) == guild.id:
                        channel = fetched
                except discord.NotFound:
                    pass
        if channel is not None:
            self._require_sheet_message_permissions(
                channel, getattr(guild, "me", None)
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
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
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
        channel = await guild.create_text_channel(
            private_map_channel_name(character.name, character.character_id),
            overwrites=overwrites,
            reason=f"Private dungeon HUD for character {character.character_id}",
        )
        PlayerViewService(self.database).bind_discord_channel(
            character.character_id, channel.id
        )
        return channel

    @staticmethod
    def _require_sheet_message_permissions(channel, bot_member) -> None:
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
                "I cannot update the existing character-sheet channel. Missing: "
                + ", ".join(f"**{name}**" for name in missing)
                + "."
            )

    async def _edit_dedicated_sheet_message(
        self, message: discord.Message, character: Character
    ) -> None:
        embeds, portrait_file = self._dedicated_sheet_presentation(character)
        try:
            await message.edit(
                embeds=embeds,
                attachments=[portrait_file] if portrait_file is not None else [],
                view=DedicatedCharacterSheetView(
                    self, character.discord_user_id, character.character_id
                ),
            )
        finally:
            if portrait_file is not None:
                portrait_file.close()

    async def _refresh_dedicated_sheet(
        self, channel, character: Character
    ) -> int:
        assert character.character_id is not None
        state = self.database.get_character_sheet_view_state(character.character_id)
        existing_message = None
        if state is not None and state.discord_message_id is not None:
            try:
                existing_message = await channel.fetch_message(state.discord_message_id)
            except discord.NotFound:
                existing_message = None
        if existing_message is not None:
            await self._edit_dedicated_sheet_message(existing_message, character)
            return existing_message.id

        embeds, portrait_file = self._dedicated_sheet_presentation(character)
        try:
            arguments = {
                "embeds": embeds,
                "view": DedicatedCharacterSheetView(
                    self, character.discord_user_id, character.character_id
                ),
            }
            if portrait_file is not None:
                arguments["file"] = portrait_file
            message = await channel.send(**arguments)
        finally:
            if portrait_file is not None:
                portrait_file.close()
        self.database.set_character_sheet_view_message(
            character.character_id, message.id
        )
        return message.id

    async def publish_character_sheet(
        self,
        interaction: discord.Interaction,
        user_id: int,
        character_id: int,
    ) -> None:
        character = self.database.get_character_by_id(user_id, character_id)
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
        message_id = self.database.get_character_sheet_message(
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
            embed, portrait_file = self._sheet_presentation(character)
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
            embed, portrait_file = self._sheet_presentation(character)
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
            self.database.set_character_sheet_message(
                guild_id, channel.id, character_id, message.id
            )

        await interaction.followup.send(
            f"{action} **{character.name}**'s sheet in this channel.",
            ephemeral=True,
        )

    def restore_default_portrait(
        self, user_id: int, character: Character
    ) -> Character:
        key = default_portrait_key(character.race, character.gender)
        updated = self.database.set_character_portrait(
            user_id, character.character_id, key
        )
        if character.portrait_key != key:
            self.portrait_store.remove(character.portrait_key)
        return updated

    async def _dm_portrait(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment | None,
        remove: bool,
    ) -> None:
        user_id = interaction.user.id
        stored_key = self.database.get_dm_portrait(user_id)
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
            self.database.set_dm_portrait(user_id, None)
            self.portrait_store.remove(current_key)
            await interaction.response.send_message(
                "Restored your default Dungeon Master portrait.", ephemeral=True
            )
            return

        if image is None:
            display_key = current_key or DEFAULT_DM_PORTRAIT_KEY
            portrait_path = self.portrait_store.path_for(display_key)
            view = DMPortraitPreviewView(self, user_id, current_key)
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
            key = await asyncio.to_thread(self.portrait_store.save_dm, user_id, content)
            try:
                self.database.set_dm_portrait(user_id, key)
            except Exception:
                self.portrait_store.remove(key)
                raise
            if current_key != key:
                self.portrait_store.remove(current_key)
        except InvalidPortraitError as error:
            await interaction.edit_original_response(content=str(error))
            return
        except (discord.HTTPException, OSError):
            await interaction.edit_original_response(
                content="The portrait could not be downloaded or saved. Please try again."
            )
            return

        portrait_path = self.portrait_store.path_for(key)
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
                view=DMPortraitPreviewView(self, user_id, key),
            )
        finally:
            portrait_file.close()

    @app_commands.command(name="create", description="Start creating your character.")
    async def create(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        flow = CharacterCreationFlow()
        self.sessions[user_id] = flow
        await interaction.response.send_message(
            creation_prompt(flow),
            view=creation_view(self, user_id, flow),
            ephemeral=True,
        )

    @app_commands.command(
        name="sheet", description="Open your active character sheet privately."
    )
    async def sheet(self, interaction: discord.Interaction) -> None:
        character = self.database.get_character(interaction.user.id)
        if character is None or character.character_id is None:
            await interaction.response.send_message(
                "You do not have an active character. Use `/character manage` first.",
                ephemeral=True,
            )
            return
        if getattr(interaction, "guild", None) is not None:
            await interaction.response.defer(ephemeral=True)
            try:
                channel = await self._ensure_dedicated_sheet_channel(
                    interaction, character
                )
                await self._refresh_dedicated_sheet(channel, character)
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
        embed, portrait_file = self._sheet_presentation(character)
        view = CharacterSheetView(
            self, interaction.user.id, character.character_id
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

    @app_commands.command(
        name="manage", description="Choose or archive one of your characters."
    )
    async def manage(self, interaction: discord.Interaction) -> None:
        characters = self.database.list_characters(interaction.user.id)
        if not characters:
            await interaction.response.send_message(
                "You have no selectable characters. Use `/character create`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            management_prompt(characters),
            view=CharacterManageView(self, interaction.user.id, characters),
            ephemeral=True,
        )

    @app_commands.command(
        name="portrait", description="View, upload, or remove your active portrait."
    )
    @app_commands.describe(
        image="Optional PNG, JPEG, or WebP image (maximum 5 MB)",
        remove="Remove the current portrait",
    )
    async def portrait(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment | None = None,
        remove: bool = False,
    ) -> None:
        character = self.database.get_character(interaction.user.id)
        if character is None or character.character_id is None:
            if is_dm(interaction):
                await self._dm_portrait(interaction, image, remove)
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
            self.restore_default_portrait(interaction.user.id, character)
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
                self,
                interaction.user.id,
                character.character_id,
                character.name,
                character.portrait_key,
            )
            portrait_path = self.portrait_store.path_for(character.portrait_key)
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
                self.portrait_store.save, character.character_id, content
            )
            try:
                updated = self.database.set_character_portrait(
                    interaction.user.id, character.character_id, key
                )
            except Exception:
                self.portrait_store.remove(key)
                raise
            if character.portrait_key and character.portrait_key != key:
                self.portrait_store.remove(character.portrait_key)
        except InvalidPortraitError as error:
            await interaction.edit_original_response(content=str(error))
            return
        except (discord.HTTPException, OSError):
            await interaction.edit_original_response(
                content="The portrait could not be downloaded or saved. Please try again."
            )
            return

        portrait_path = self.portrait_store.path_for(updated.portrait_key)
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
            self,
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

    @app_commands.command(
        name="removeportrait", description="Remove your active character's portrait."
    )
    async def remove_portrait(self, interaction: discord.Interaction) -> None:
        character = self.database.get_character(interaction.user.id)
        if character is None or character.character_id is None:
            if is_dm(interaction):
                await self._dm_portrait(interaction, None, True)
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
        self.restore_default_portrait(interaction.user.id, character)
        await interaction.response.send_message(
            f"Restored **{character.name}**'s default portrait.", ephemeral=True
        )

    async def submit_component(
        self, interaction: discord.Interaction, user_id: int, value: object
    ) -> None:
        flow = self.sessions.get(user_id)
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
                view=creation_view(self, user_id, flow),
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
                view=creation_view(self, user_id, flow),
            )
            return

        result = flow.result
        if result is None:
            raise RuntimeError("Completed creation flow has no result.")
        previous = self.database.get_character(user_id)
        try:
            character = self.service.persist(user_id, result)
        except CharacterAlreadyExistsError as error:
            self.sessions.pop(user_id, None)
            await interaction.response.edit_message(content=str(error), view=None)
            return
        self.sessions.pop(user_id, None)
        await interaction.response.edit_message(
            content=(
                f"Created **{character.name}** with {character.max_hp} HP.\n"
                f"{result.summary}"
            ),
            view=None,
        )
        await self.active_character_changed(interaction, previous, character)

    async def back_component(
        self, interaction: discord.Interaction, user_id: int
    ) -> None:
        flow = self.sessions.get(user_id)
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
            view=creation_view(self, user_id, flow),
        )

    @app_commands.command(name="cancel", description="Cancel character creation.")
    async def cancel(self, interaction: discord.Interaction) -> None:
        removed = self.sessions.pop(interaction.user.id, None)
        message = (
            "Character creation cancelled."
            if removed is not None
            else "You do not have an active character creation session."
        )
        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        CharacterCommands(
            bot.database,
            CharacterPortraitStore(
                getattr(
                    getattr(bot, "config", None),
                    "character_media_path",
                    "data/characters",
                )
            ),
            bot,
        )
    )
