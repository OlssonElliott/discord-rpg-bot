"""Combat item-use orchestration."""

from __future__ import annotations

from .errors import CombatError
from .models import CombatScene, CombatantKind
from ..characters.models import CharacterCombatStatus
from ..inventory import ItemType


class CombatItemMixin:
    """Use supported carried consumables as a Standard Action."""

    def use_item(
        self,
        guild_id: int,
        item_instance_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        actor = scene.current_combatant()
        if actor is None:
            raise CombatError("There is no current combatant.")
        if actor.kind is not CombatantKind.CHARACTER:
            raise CombatError("Only a character can use items in combat.")
        if actor.standard_action_spent:
            raise CombatError(
                f"{actor.name} has already spent their Standard Action."
            )

        character = self._character_by_source_id(actor.source_id)
        assert character.character_id is not None
        character_id = character.character_id
        state = self.database.get_character_combat_state(character_id)
        if state.status not in {
            CharacterCombatStatus.ACTIVE,
            CharacterCombatStatus.RECOVERING,
        }:
            raise CombatError(
                f"{actor.name} cannot use an item while {state.status.value}."
            )

        inventory = self.database.get_character_inventory(character_id)
        try:
            item = inventory.item(item_instance_id)
            template = self.world.catalog.get(item.template_id)
        except ValueError as error:
            raise CombatError(str(error)) from error

        if template.item_type is not ItemType.CONSUMABLE:
            raise CombatError(f"{template.name} is not a consumable.")
        if template.affected_amount is None:
            raise CombatError(
                f"{template.name} does not have a supported combat effect yet."
            )

        if template.affected_stat == "hp":
            if character.hp >= character.max_hp:
                raise CombatError(f"{actor.name} is already at full HP.")
            before = character.hp
            updated = self.database.heal_character_by_id(
                character_id,
                template.affected_amount,
            )
            effect_message = (
                f"recovered {updated.hp - before} HP "
                f"({updated.hp}/{updated.max_hp} HP)"
            )
        elif template.affected_stat == "hunger":
            if character.hunger <= 0:
                raise CombatError(f"{actor.name} is not hungry.")
            before = character.hunger
            updated = self.database.adjust_character_hunger(
                character_id,
                -template.affected_amount,
            )
            effect_message = (
                f"reduced Hunger by {before - updated.hunger} "
                f"({updated.hunger}/100 Hunger)"
            )
        else:
            raise CombatError(
                f"{template.name} does not have a supported combat effect yet."
            )

        try:
            self.database.set_inventory_item_quantity(
                character_id,
                item.instance_id,
                item.quantity - 1,
            )
            self.repository.set_standard_action_spent(
                scene.id,
                actor.kind,
                actor.source_id,
                True,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "item_used",
                f"{actor.name} used {template.name} and {effect_message}.",
                actor_kind=actor.kind,
                actor_source_id=actor.source_id,
                actor_name=actor.name,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error

        return self._require_current(guild_id)
