"""Discord UI for deterministic character creation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import discord

from ...character_creation import CharacterCreationFlow, CreationStep
from ...character_creation.rules import ATTRIBUTES, STANDARD_ARRAY
from .presentation import attribute_prompt, bonus_prompt

if TYPE_CHECKING:
    from .cog import CharacterCommands


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
            options=[
                discord.SelectOption(label=choice, value=choice)
                for choice in choices
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.submit_component(
            interaction,
            self.user_id,
            self.values[0],
        )


class ChoiceView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        choices: tuple[str, ...],
        placeholder: str,
    ) -> None:
        super().__init__(cog, user_id)
        self.add_item(
            ChoiceSelect(cog, user_id, choices, placeholder)
        )
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
        await self.cog.submit_component(
            interaction,
            self.user_id,
            str(self.name),
        )


class NameButton(discord.ui.Button):
    def __init__(self, cog: CharacterCommands, user_id: int) -> None:
        super().__init__(
            label="Enter name",
            style=discord.ButtonStyle.primary,
            emoji="✏️",
        )
        self.cog = cog
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            NameModal(self.cog, self.user_id)
        )


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
            content=attribute_prompt(view.assignments),
            view=view,
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
            if (
                previous_attribute is not None
                and previous_value is not None
            ):
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
            content=attribute_prompt(assignments),
            view=view,
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
        await interaction.response.edit_message(
            content=attribute_prompt({}),
            view=view,
        )


class ConfirmAttributesButton(discord.ui.Button):
    def __init__(self, attribute_view: AttributeView) -> None:
        self.attribute_view = attribute_view
        super().__init__(
            label="Confirm attributes",
            style=discord.ButtonStyle.primary,
            disabled=(
                set(attribute_view.assignments) != set(ATTRIBUTES)
                or set(attribute_view.assignments.values())
                != set(STANDARD_ARRAY)
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
            self.add_item(
                AttributeNumberButton(
                    self,
                    value,
                    0 if index < 5 else 1,
                )
            )
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
            content=bonus_prompt(
                self.bonus_view.flow,
                points,
            ),
            view=view,
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
            self.add_item(
                BonusButton(self, attribute, 1, row)
            )
            self.add_item(
                BonusButton(self, attribute, -1, row)
            )
        self.add_item(ConfirmBonusButton(self))
        self.add_item(BackButton(self, row=3))


class SkillSelect(discord.ui.Select):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        choices: tuple[str, ...],
    ) -> None:
        self.cog = cog
        self.user_id = user_id
        super().__init__(
            placeholder="Choose two skill trees",
            min_values=2,
            max_values=2,
            options=[
                discord.SelectOption(label=choice, value=choice)
                for choice in choices
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.submit_component(
            interaction,
            self.user_id,
            tuple(self.values),
        )


class SkillView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        choices: tuple[str, ...],
    ) -> None:
        super().__init__(cog, user_id)
        self.add_item(
            SkillSelect(cog, user_id, choices)
        )
        self.add_item(BackButton(self))


def creation_view(
    cog: CharacterCommands,
    user_id: int,
    flow: CharacterCreationFlow,
) -> discord.ui.View:
    step = flow.current_step
    if step in {
        CreationStep.LINEAGE,
        CreationStep.RACE,
        CreationStep.AGE,
        CreationStep.GENDER,
    }:
        return ChoiceView(
            cog,
            user_id,
            flow.valid_choices(),
            f"Choose {step.value}",
        )
    if step is CreationStep.NAME:
        return NameView(cog, user_id)
    if step is CreationStep.ATTRIBUTES:
        return AttributeView(cog, user_id)
    if step is CreationStep.BONUS_POINTS:
        return BonusView(cog, user_id, flow)
    if step is CreationStep.SKILLS:
        return SkillView(
            cog,
            user_id,
            flow.valid_choices(),
        )
    raise ValueError(f"No component view for {step.value}.")
