"""Interactive Discord adapter for deterministic character creation."""

from __future__ import annotations

from collections.abc import Mapping

import discord
from discord import app_commands
from discord.ext import commands

from ..character_creation import (
    CharacterCreationFlow,
    CharacterCreationValidationError,
    CreationStep,
)
from ..character_creation.rules import ATTRIBUTES, STANDARD_ARRAY
from ..character_creation.service import CharacterCreationService
from ..database import CharacterAlreadyExistsError, CharacterNotFoundError, Database
from ..models import Character


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


def bonus_prompt(points: Mapping[str, int]) -> str:
    total = sum(points.values())
    allocation = " · ".join(
        f"{attribute} **+{points.get(attribute, 0)}**" for attribute in ATTRIBUTES
    )
    return (
        f"{creation_prompt_for_step(CreationStep.BONUS_POINTS)}\n"
        f"{allocation}\nRemaining: **{2 - total}**"
    )


class OwnedView(discord.ui.View):
    def __init__(self, cog: CharacterCommands, user_id: int) -> None:
        super().__init__(timeout=15 * 60)
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
        view = BonusView(self.bonus_view.cog, self.bonus_view.user_id, points)
        await interaction.response.edit_message(content=bonus_prompt(points), view=view)


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
        points: Mapping[str, int] | None = None,
    ) -> None:
        super().__init__(cog, user_id)
        self.points = dict(points or {})
        for index, attribute in enumerate(ATTRIBUTES):
            row = index // 2
            self.add_item(BonusButton(self, attribute, 1, row))
            self.add_item(BonusButton(self, attribute, -1, row))
        self.add_item(ConfirmBonusButton(self))


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
        lines.append(f"• {character.name}{suffix}")
    lines.append("Choose a character, then activate or archive it.")
    return "\n".join(lines)


class CharacterSelect(discord.ui.Select):
    def __init__(
        self,
        manage_view: CharacterManageView,
        characters: list[Character],
    ) -> None:
        self.manage_view = manage_view
        super().__init__(
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
            label="Use character",
            style=discord.ButtonStyle.primary,
            disabled=selected is None or selected.is_active,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_id = self.manage_view.selected_id
        if selected_id is None:
            return
        try:
            self.manage_view.cog.database.select_character(
                self.manage_view.user_id, selected_id
            )
        except CharacterNotFoundError as error:
            await interaction.response.edit_message(content=str(error), view=None)
            return
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


class ArchiveCharacterButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        super().__init__(
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
        super().__init__(cog, user_id)
        self.characters = characters
        self.selected_id = selected_id
        self.add_item(CharacterSelect(self, characters))
        self.add_item(ActivateCharacterButton(self))
        self.add_item(ArchiveCharacterButton(self))


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
        return BonusView(cog, user_id)
    if step is CreationStep.SKILLS:
        return SkillView(cog, user_id, flow.valid_choices())
    raise ValueError(f"No component view for {step.value}.")


class CharacterCommands(commands.GroupCog, group_name="character"):
    """Tracks transient flows per Discord user; only results are persisted."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.service = CharacterCreationService(database)
        self.sessions: dict[int, CharacterCreationFlow] = {}

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
                else bonus_prompt({})
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
    await bot.add_cog(CharacterCommands(bot.database))
