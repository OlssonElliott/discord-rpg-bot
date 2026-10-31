"""Discord combat controls backed exclusively by the shared CombatService."""

import asyncio
import logging
from hashlib import sha256

import discord

from dataclasses import dataclass

from ..combat.models import (
    CombatScene,
    CombatantKind,
    CombatantState,
    LandmarkRelation,
)
from ..combat.navigation import movement_legs
from ..combat.service import CombatError
from ..map_renderer.combat import render_combat_map

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MoveDestination:
    """One reachable combat location and stance for the player's turn."""

    landmark_id: str
    name: str
    relation: LandmarkRelation
    cost: int


def move_destinations(
    scene: CombatScene,
    actor: CombatantState,
) -> list[MoveDestination]:
    """Offer reachable locations and only the next partly traversable ones.

    A long route may contain several landmarks. If movement runs out while
    crossing one connection, only that connection's endpoint is a meaningful
    partial destination; landmarks farther along the same path are not offered.
    """

    destinations: list[MoveDestination] = []
    for landmark in scene.landmarks:
        try:
            legs = movement_legs(scene, actor, landmark.id)
        except ValueError:
            continue  # No valid unblocked route to this location.

        cost = sum(
            route.movement_cost - already_moved
            for _, _, route, already_moved in legs
        )
        if not actor.is_between_landmarks and actor.landmark_id == landmark.id:
            continue
        if cost > actor.movement_remaining:
            # Only offer PARTIAL when the player can actually enter the final
            # connection toward this location. Reaching a preceding node with
            # 0 MP remaining does not count as moving toward a farther node.
            spent_before_final_leg = 0
            for _, _, route, already_moved in legs[:-1]:
                spent_before_final_leg += route.movement_cost - already_moved
            if actor.movement_remaining <= spent_before_final_leg:
                continue
        if cost > 0 and actor.movement_remaining <= 0:
            continue

        destinations.append(
            MoveDestination(
                landmark.id,
                landmark.name,
                LandmarkRelation.AT,
                cost,
            )
        )
    return sorted(
        destinations,
        key=lambda destination: (
            destination.cost,
            destination.name.casefold(),
            destination.relation.value,
        ),
    )



async def _update_move_preview(interaction, scene, actor, view):
    """Replace only the private move panel's map, never the public combat card."""
    costs = {destination.landmark_id: destination.cost for destination in view.destinations}
    try:
        rendered = await asyncio.to_thread(
            render_combat_map,
            scene, scene.room_id,
            move_costs=costs,
            movement_remaining=actor.movement_remaining,
        )
        filename = f"move-map-{sha256(rendered.getvalue()).hexdigest()[:12]}.png"
        await interaction.edit_original_response(
            content=view.prompt(scene, actor),
            embed=discord.Embed(
                title=f"Move · {actor.name}",
                description="Choose a location from the menu below.",
                color=discord.Colour.from_rgb(65, 119, 103),
            ).set_image(url=f"attachment://{filename}"),
            attachments=[discord.File(rendered, filename=filename)],
            view=view,
        )
    except Exception:
        LOGGER.exception("Unable to display movement map")
        # Keep Move playable even if Pillow/Discord attachment upload fails.
        await interaction.edit_original_response(
            content=view.prompt(scene, actor),
            embed=None,
            attachments=[],
            view=view,
        )


class CombatActionView(discord.ui.View):
    """An ephemeral turn menu. Every action rechecks scene and ownership."""

    def __init__(self, cog, scene_id: int, character_id: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.scene_id = scene_id
        self.character_id = character_id

    def _check(self, interaction):
        scene = self.cog.service.current(interaction.guild_id)
        if scene is None or scene.id != self.scene_id:
            raise CombatError("This encounter is no longer active.")
        actor = scene.current_combatant()
        if actor is None or actor.kind is not CombatantKind.CHARACTER:
            raise CombatError("It is not a player character's turn.")
        if actor.source_id != self.character_id:
            raise CombatError("The turn has changed. Open the current controls.")
        character = self.cog.database.get_character(interaction.user.id)
        if character is None or str(character.character_id) != self.character_id:
            raise CombatError("Only the active character's owner can act.")
        return scene, actor

    async def _perform(self, interaction, action):
        try:
            self._check(interaction)
            if action == "defend":
                self.cog.service.defend(interaction.guild_id)
            elif action == "dash":
                self.cog.service.dash(interaction.guild_id)
            elif action == "end":
                self.cog.service.next_turn(interaction.guild_id)
            else:
                raise CombatError("Unknown combat action.")
        except (CombatError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"{action.capitalize()} completed.", view=None,
        )
        scene = self.cog.service.current(interaction.guild_id)
        if scene is not None:
            await self.cog._publish_scene(interaction.guild, scene)

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.primary)
    async def attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            scene, actor = self._check(interaction)
            if actor.standard_action_spent:
                raise CombatError("Your Standard Action is already spent.")
            options = [
                discord.SelectOption(label=enemy.name[:100], value=enemy.source_id)
                for enemy in scene.combatants
                if enemy.kind is CombatantKind.ENEMY
                and self.cog.world.get_enemy(enemy.source_id) is not None
                and self.cog.world.get_enemy(enemy.source_id).current_hp > 0
            ][:25]
            if not options:
                raise CombatError("No living enemies are available to target.")
        except (CombatError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        view = CombatTargetView(self.cog, self.scene_id, self.character_id, options)
        await interaction.response.edit_message(content="Choose an enemy to attack:", view=view)

    @discord.ui.button(label="Move", style=discord.ButtonStyle.secondary)
    async def move(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            scene, actor = await asyncio.to_thread(self._check, interaction)
            options = await asyncio.to_thread(move_destinations, scene, actor)
            if not options:
                raise CombatError("No locations can be reached with your remaining movement.")
        except (CombatError, ValueError) as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            LOGGER.exception("Could not open combat movement menu")
            await interaction.followup.send("Could not open Move. Check bot logs.", ephemeral=True)
            return

        view = CombatMoveView(self.cog, self.scene_id, self.character_id, options)
        await _update_move_preview(interaction, scene, actor, view)

    @discord.ui.button(label="Defend", style=discord.ButtonStyle.secondary)
    async def defend(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._perform(interaction, "defend")

    @discord.ui.button(label="Dash", style=discord.ButtonStyle.secondary)
    async def dash(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._perform(interaction, "dash")

    @discord.ui.button(label="End turn", style=discord.ButtonStyle.danger)
    async def end(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._perform(interaction, "end")


class CombatTargetSelect(discord.ui.Select):
    def __init__(self, view, options):
        super().__init__(placeholder="Select an enemy", options=options)
        self.target_view = view

    async def callback(self, interaction: discord.Interaction):
        try:
            self.target_view._check(interaction)
            scene, result = self.target_view.cog.service.attack_enemy(
                interaction.guild_id, self.values[0],
            )
        except (CombatError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.edit_message(
            content=(
                f"{result.attacker_name} attacked {result.target_name}: "
                f"{'Hit' if result.hit else 'Miss'}"
                f" · {result.final_damage} damage · "
                f"{result.target_hp}/{result.target_max_hp} HP."
            ),
            view=None,
        )
        await self.target_view.cog._publish_scene(interaction.guild, scene)


class CombatTargetView(discord.ui.View):
    def __init__(self, cog, scene_id, character_id, options):
        super().__init__(timeout=180)
        self.cog = cog
        self.scene_id = scene_id
        self.character_id = character_id
        self.add_item(CombatTargetSelect(self, options))

    _check = CombatActionView._check


class CombatMoveSelect(discord.ui.Select):
    """Choose a location; CombatService revalidates distance and movement."""

    def __init__(self, move_view):
        self.move_view = move_view
        first = move_view.page * 25
        page_destinations = move_view.destinations[first:first + 25]
        options = []
        for index, destination in enumerate(page_destinations, start=first):
            stance = " · Behind cover" if destination.relation is LandmarkRelation.BEHIND else ""
            progress = (
                "Arrive" if destination.cost <= move_view.movement_remaining
                else "Partial movement"
            )
            options.append(discord.SelectOption(
                label=f"{destination.name}{stance}"[:100],
                value=str(index),
                description=f"{destination.cost} movement · {progress}"[:100],
            ))
        super().__init__(
            placeholder="Choose a location",
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = self.move_view
        try:
            scene, actor = await asyncio.to_thread(view._check, interaction)
            destination = view.destinations[int(self.values[0])]
            # The scene may have changed in the DM dashboard since this
            # menu was displayed. Recompute availability before mutating.
            allowed = await asyncio.to_thread(move_destinations, scene, actor)
            if destination not in allowed:
                raise CombatError(
                    "That destination is no longer reachable. Open Move again."
                )
            updated = await asyncio.to_thread(
                view.cog.service.move_combatant_toward,
                interaction.guild_id,
                CombatantKind.CHARACTER,
                view.character_id,
                destination.landmark_id,
                destination.relation,
            )
        except (CombatError, ValueError, IndexError) as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            LOGGER.exception("Move failed")
            await interaction.followup.send("Movement failed. Check bot logs.", ephemeral=True)
            return

        moved = updated.current_combatant()
        assert moved is not None
        if moved.is_between_landmarks:
            source = updated.landmark(moved.route_source_landmark_id)
            target = updated.landmark(moved.route_destination_landmark_id)
            where = (
                f"between {source.name if source else moved.route_source_landmark_id} "
                f"and {target.name if target else moved.route_destination_landmark_id}"
                f" ({moved.route_progress}/{moved.route_cost})"
            )
        else:
            location = updated.landmark(moved.landmark_id)
            where = f"{moved.relation.value} {location.name if location else moved.landmark_id}"
        await interaction.edit_original_response(
            content=(
                f"{moved.name} moved {where}. "
                f"Movement remaining: {moved.movement_remaining}."
            ),
            embed=None,
            attachments=[],
            view=None,
        )
        await view.cog._publish_scene(interaction.guild, updated)


class CombatMoveView(discord.ui.View):
    """Paginated location picker for the current character's combat turn."""

    _check = CombatActionView._check

    def __init__(self, cog, scene_id, character_id, destinations, page=0):
        super().__init__(timeout=180)
        self.cog = cog
        self.scene_id = scene_id
        self.character_id = character_id
        self.destinations = destinations
        self.page = page
        self.movement_remaining = 0
        # Will be populated with the actor's actual budget before display.
        self._populate(remaining=0)

    def _populate(self, remaining: int):
        self.movement_remaining = remaining
        self.clear_items()
        self.add_item(CombatMoveSelect(self))
        self.add_item(CombatMovePageButton(self, "Previous", -1))
        self.add_item(CombatMovePageButton(self, "Next", 1))

    def prompt(self, scene, actor):
        self._populate(actor.movement_remaining)
        location = scene.landmark(actor.landmark_id)
        if actor.is_between_landmarks:
            origin = scene.landmark(actor.route_source_landmark_id)
            target = scene.landmark(actor.route_destination_landmark_id)
            position = (
                f"Between {origin.name if origin else actor.route_source_landmark_id} "
                f"and {target.name if target else actor.route_destination_landmark_id}"
                f" ({actor.route_progress}/{actor.route_cost})"
            )
        else:
            position = location.name if location else actor.landmark_id
        return (
            f"**Move · {actor.name}**\n"
            f"Current location: {position}\n"
            f"Movement remaining: {actor.movement_remaining}\n"
            "Choose a destination. Longer routes use your remaining movement "
            "and may leave you between locations."
        )


class CombatMovePageButton(discord.ui.Button):
    def __init__(self, move_view, label, direction):
        self.move_view = move_view
        self.direction = direction
        page_count = (len(move_view.destinations) + 24) // 25
        target = move_view.page + direction
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=1,
            disabled=not (0 <= target < page_count),
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            scene, actor = await asyncio.to_thread(self.move_view._check, interaction)
        except (CombatError, ValueError) as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        view = CombatMoveView(
            self.move_view.cog,
            self.move_view.scene_id,
            self.move_view.character_id,
            await asyncio.to_thread(move_destinations, scene, actor),
            page=self.move_view.page + self.direction,
        )
        if not (0 <= view.page * 25 < len(view.destinations)):
            await interaction.followup.send(
                "These locations are no longer available. Open Move again.",
                ephemeral=True,
            )
            return
        await _update_move_preview(interaction, scene, actor, view)
