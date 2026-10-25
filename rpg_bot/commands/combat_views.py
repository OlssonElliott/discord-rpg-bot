"""Discord combat controls backed exclusively by the shared CombatService."""

import discord

from ..combat.models import CombatantKind
from ..combat.service import CombatError


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


class CombatTargetView(CombatActionView):
    def __init__(self, cog, scene_id, character_id, options):
        discord.ui.View.__init__(self, timeout=180)
        self.cog = cog
        self.scene_id = scene_id
        self.character_id = character_id
        self.add_item(CombatTargetSelect(self, options))
