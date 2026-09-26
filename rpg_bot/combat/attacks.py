"""Combat attack orchestration."""

from __future__ import annotations

import math

from .errors import CombatError
from .models import (
    AttackResult,
    CombatScene,
    CombatantKind,
    DamageRoll,
    EnemyAttackResult,
)
from .navigation import same_combat_position, tactical_distance
from ..inventory import DamagePart
from ..characters.models import CharacterCombatStatus
from ..world.enemies import EnemyStatus


class CombatAttackMixin:
    """Character and enemy attack actions."""

    def attack_enemy(
        self,
        guild_id: int,
        target_enemy_id: str,
    ) -> tuple[CombatScene, AttackResult]:
        scene = self._require_current(guild_id)
        attacker = scene.current_combatant()
        if attacker is None:
            raise CombatError("There is no current combatant.")
        if attacker.kind is not CombatantKind.CHARACTER:
            raise CombatError(
                "Enemy attacks are not implemented in this combat slice yet."
            )
        if attacker.standard_action_spent:
            raise CombatError(
                f"{attacker.name} has already spent their Standard Action."
            )

        target = next(
            (
                combatant
                for combatant in scene.combatants
                if combatant.kind is CombatantKind.ENEMY
                and combatant.source_id == target_enemy_id
            ),
            None,
        )
        if target is None:
            raise CombatError(
                f"Enemy '{target_enemy_id}' is not in the active combat."
            )
        enemy = self.world.get_enemy(target_enemy_id)
        if enemy is None:
            raise CombatError(
                "This legacy enemy has no combat stats. "
                "Use a structured enemy type for attacks."
            )
        if enemy.status is not EnemyStatus.ACTIVE or enemy.current_hp <= 0:
            raise CombatError(f"{enemy.name} is no longer an active target.")

        template = self.world.get_enemy_template(enemy.template_id)
        if template is None:
            raise CombatError(
                f"Enemy template '{enemy.template_id}' does not exist."
            )

        character = self._character_by_source_id(attacker.source_id)
        assert character.character_id is not None
        character_id = character.character_id
        character_state = self.database.get_character_combat_state(
            character_id
        )
        if character_state.status not in {
            CharacterCombatStatus.ACTIVE,
            CharacterCombatStatus.RECOVERING,
        }:
            raise CombatError(
                f"{attacker.name} cannot attack while "
                f"{character_state.status.value}."
            )

        weapon = self._equipped_attack_weapon(character_id)
        weapon_name = weapon.name if weapon is not None else "Unarmed"
        weapon_range = weapon.range if weapon is not None else 0
        if weapon_range <= 0:
            if not same_combat_position(attacker, target):
                raise CombatError(
                    f"{target.name} is not within melee range of "
                    f"{attacker.name}."
                )
        else:
            distance = tactical_distance(scene, attacker, target)
            if distance is None:
                raise CombatError(
                    f"No clear route reaches {target.name}."
                )
            if distance > weapon_range:
                raise CombatError(
                    f"{target.name} is out of range "
                    f"({distance}/{weapon_range})."
                )

        attack_attribute = self._weapon_attack_attribute(weapon)
        attribute_score = self.database.get_character_attribute(
            character_id,
            attack_attribute,
        )
        attack_modifier = (attribute_score - 10) // 2
        recovering = (
            character_state.status is CharacterCombatStatus.RECOVERING
        )
        attack_rolls, attack_roll = self._roll_d20(
            disadvantage=recovering,
        )
        attack_total = attack_roll + attack_modifier
        critical = attack_roll == 20
        hit = critical or (
            attack_roll != 1
            and attack_total >= template.defense_dc
        )

        damage_rolls: tuple[DamageRoll, ...] = ()
        raw_damage = 0
        reduction = 0
        reduction_type = "armor"
        final_damage = 0
        target_hp = enemy.current_hp
        target_defeated = False

        if hit:
            damage_parts = (
                weapon.damage_parts
                if weapon is not None and weapon.damage_parts
                else (DamagePart(4, "blunt"),)
            )
            damage_rolls = tuple(
                DamageRoll(
                    die=max(1, part.amount),
                    damage_type=part.damage_type,
                    roll=(
                        max(1, part.amount)
                        if critical
                        else self._roll_die(max(1, part.amount))
                    ),
                )
                for part in damage_parts
            )
            raw_damage = sum(part.roll for part in damage_rolls)
            magical_types = {
                "arcane",
                "cold",
                "fire",
                "lightning",
                "magic",
                "necrotic",
                "psychic",
                "radiant",
            }
            damage_types = {
                part.damage_type.casefold()
                for part in damage_rolls
            }
            if damage_types and damage_types <= magical_types:
                reduction_type = "magical_resistance"
                reduction = max(0, template.magical_resistance)
            else:
                reduction = max(0, template.armor)
            final_damage = max(1, raw_damage - reduction)
            target_hp = max(0, enemy.current_hp - final_damage)
            updated_enemy = self.world.update_enemy(
                enemy.id,
                name=enemy.name,
                description=enemy.description,
                current_hp=target_hp,
            )
            target_hp = updated_enemy.current_hp
            target_defeated = target_hp == 0

        result = AttackResult(
            attacker_kind=attacker.kind,
            attacker_source_id=attacker.source_id,
            attacker_name=attacker.name,
            target_kind=target.kind,
            target_source_id=target.source_id,
            target_name=target.name,
            weapon_name=weapon_name,
            attack_attribute=attack_attribute,
            attack_roll=attack_roll,
            attack_modifier=attack_modifier,
            attack_total=attack_total,
            defense_dc=template.defense_dc,
            hit=hit,
            critical=critical,
            damage_rolls=damage_rolls,
            raw_damage=raw_damage,
            reduction=reduction,
            reduction_type=reduction_type,
            final_damage=final_damage,
            target_hp=target_hp,
            target_max_hp=template.max_hp,
            target_defeated=target_defeated,
        )

        try:
            self.repository.set_standard_action_spent(
                scene.id,
                attacker.kind,
                attacker.source_id,
                True,
            )

            if hit:
                critical_text = " critical" if critical else ""
                reduction_label = reduction_type.replace("_", " ")
                roll_text = (
                    f"{'/'.join(str(value) for value in attack_rolls)} "
                    f"-> {attack_roll}"
                    if recovering
                    else str(attack_roll)
                )
                message = (
                    f"{attacker.name} attacked {target.name} with "
                    f"{weapon_name}: {roll_text}"
                    f"{attack_modifier:+d} = {attack_total} vs "
                    f"Defense {template.defense_dc},"
                    f"{critical_text} hit for {final_damage} damage "
                    f"({raw_damage} raw, {reduction} "
                    f"{reduction_label} reduction). "
                    f"{target.name} has {target_hp}/{template.max_hp} HP."
                )
            else:
                roll_text = (
                    f"{'/'.join(str(value) for value in attack_rolls)} "
                    f"-> {attack_roll}"
                    if recovering
                    else str(attack_roll)
                )
                message = (
                    f"{attacker.name} attacked {target.name} with "
                    f"{weapon_name}: {roll_text}"
                    f"{attack_modifier:+d} = {attack_total} vs "
                    f"Defense {template.defense_dc}, miss."
                )

            self.repository.append_log(
                scene.id,
                scene.round_number,
                "attack_resolved",
                message,
                actor_kind=attacker.kind,
                actor_source_id=attacker.source_id,
                actor_name=attacker.name,
            )

            if target_defeated:
                self.repository.remove_combatant(
                    scene.id,
                    CombatantKind.ENEMY,
                    target.source_id,
                )
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_defeated",
                    f"{target.name} was defeated.",
                    actor_kind=target.kind,
                    actor_source_id=target.source_id,
                    actor_name=target.name,
                )
        except ValueError as error:
            raise CombatError(str(error)) from error

        return self._require_current(guild_id), result

    def attack_character(
        self,
        guild_id: int,
        target_character_id: str,
    ) -> tuple[CombatScene, EnemyAttackResult]:
        scene = self._require_current(guild_id)
        attacker = scene.current_combatant()
        if attacker is None:
            raise CombatError("There is no current combatant.")
        if attacker.kind is not CombatantKind.ENEMY:
            raise CombatError(
                "Only an enemy can use this attack action."
            )
        if attacker.standard_action_spent:
            raise CombatError(
                f"{attacker.name} has already spent their Standard Action."
            )

        target = next(
            (
                combatant
                for combatant in scene.combatants
                if combatant.kind is CombatantKind.CHARACTER
                and combatant.source_id == target_character_id
            ),
            None,
        )
        if target is None:
            raise CombatError(
                f"Character '{target_character_id}' is not in the active combat."
            )
        enemy = self.world.get_enemy(attacker.source_id)
        if enemy is None:
            raise CombatError(
                "This legacy enemy has no combat stats. "
                "Use a structured enemy type for attacks."
            )
        if enemy.status is not EnemyStatus.ACTIVE or enemy.current_hp <= 0:
            raise CombatError(f"{enemy.name} is no longer able to attack.")

        template = self.world.get_enemy_template(enemy.template_id)
        if template is None:
            raise CombatError(
                f"Enemy template '{enemy.template_id}' does not exist."
            )

        enemy_weapon = None
        if template.main_hand_item_id is not None:
            try:
                candidate = self.world.catalog.get(
                    template.main_hand_item_id
                )
                if candidate.item_type.value == "weapon":
                    enemy_weapon = candidate
            except ValueError:
                enemy_weapon = None

        weapon_range = enemy_weapon.range if enemy_weapon is not None else 0
        if weapon_range <= 0:
            if not same_combat_position(attacker, target):
                raise CombatError(
                    f"{target.name} is not within melee range of "
                    f"{attacker.name}."
                )
        else:
            distance = tactical_distance(scene, attacker, target)
            if distance is None:
                raise CombatError(
                    f"No clear route reaches {target.name}."
                )
            if distance > weapon_range:
                raise CombatError(
                    f"{target.name} is out of range "
                    f"({distance}/{weapon_range})."
                )

        character = self._character_by_source_id(target.source_id)
        assert character.character_id is not None
        character_id = character.character_id
        character_state = self.database.get_character_combat_state(
            character_id
        )
        if character_state.status not in {
            CharacterCombatStatus.ACTIVE,
            CharacterCombatStatus.RECOVERING,
        }:
            raise CombatError(
                f"{character.name} cannot defend while "
                f"{character_state.status.value}."
            )

        (
            defense_method,
            defense_attribute,
            defense_modifier,
        ) = self._automatic_defense(character_id)

        recovering = (
            character_state.status is CharacterCombatStatus.RECOVERING
        )
        defending = target.defending
        defense_rolls, defense_roll = self._roll_d20(
            advantage=defending,
            disadvantage=recovering,
        )
        defense_total = defense_roll + defense_modifier
        critical_defense = defense_roll == 20
        defended = critical_defense or (
            defense_roll != 1
            and defense_total >= template.attack_dc
        )

        damage_rolls: tuple[int, ...] = ()
        raw_damage = 0
        armor_reduction = 0
        final_damage = 0
        target_hp = character.hp

        if not defended:
            damage_rolls, raw_damage = self._roll_damage_expression(
                template.damage
            )
            armor_reduction, _ = self._equipped_armor_stats(character_id)
            if raw_damage > 0:
                final_damage = max(
                    1,
                    raw_damage - armor_reduction,
                )
                updated_character = self.database.damage_character_by_id(
                    character_id,
                    final_damage,
                )
                self.repository.add_damage_taken(
                    scene.id,
                    target.kind,
                    target.source_id,
                    final_damage,
                )
                target_hp = updated_character.hp

        updated_character_state = self.database.get_character_combat_state(
            character_id
        )
        target_down = (
            updated_character_state.status is CharacterCombatStatus.DOWNED
        )
        target_dead = (
            updated_character_state.status is CharacterCombatStatus.DEAD
        )

        result = EnemyAttackResult(
            attacker_source_id=attacker.source_id,
            attacker_name=attacker.name,
            target_source_id=target.source_id,
            target_name=target.name,
            attack_profile=template.attack_profile,
            attack_dc=template.attack_dc,
            defense_method=defense_method,
            defense_attribute=defense_attribute,
            defense_roll=defense_roll,
            defense_modifier=defense_modifier,
            defense_total=defense_total,
            defended=defended,
            critical_defense=critical_defense,
            damage_expression=template.damage,
            damage_rolls=damage_rolls,
            raw_damage=raw_damage,
            armor_reduction=armor_reduction,
            final_damage=final_damage,
            target_hp=target_hp,
            target_max_hp=character.max_hp,
            target_down=target_down,
            target_status=updated_character_state.status.value,
            target_dead=target_dead,
        )

        try:
            self.repository.set_standard_action_spent(
                scene.id,
                attacker.kind,
                attacker.source_id,
                True,
            )
            if defending:
                self.repository.set_defending(
                    scene.id,
                    target.kind,
                    target.source_id,
                    False,
                )

            defense_label = defense_method.replace("_", " ")
            defense_roll_text = (
                f"{'/'.join(str(value) for value in defense_rolls)} "
                f"-> {defense_roll}"
                if len(defense_rolls) > 1
                else str(defense_roll)
            )
            defend_text = " with Defend Advantage" if defending else ""
            if defended:
                message = (
                    f"{attacker.name} attacked {target.name} with "
                    f"{template.attack_profile}. "
                    f"{target.name} automatically used {defense_label}{defend_text}: "
                    f"{defense_roll_text}{defense_modifier:+d} = "
                    f"{defense_total} vs Attack DC {template.attack_dc}, "
                    f"defended."
                )
            else:
                message = (
                    f"{attacker.name} attacked {target.name} with "
                    f"{template.attack_profile}. "
                    f"{target.name} automatically used {defense_label}{defend_text}: "
                    f"{defense_roll_text}{defense_modifier:+d} = "
                    f"{defense_total} vs Attack DC {template.attack_dc}, "
                    f"failed. {final_damage} damage "
                    f"({raw_damage} raw, {armor_reduction} armor reduction). "
                    f"{target.name} has {target_hp}/{character.max_hp} HP."
                )

            self.repository.append_log(
                scene.id,
                scene.round_number,
                "enemy_attack_resolved",
                message,
                actor_kind=attacker.kind,
                actor_source_id=attacker.source_id,
                actor_name=attacker.name,
            )

            if target_down:
                death_save_dc = 10 + math.ceil(abs(target_hp) / 2)
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_downed",
                    (
                        f"{target.name} was downed at {target_hp} HP. "
                        f"Death Save DC is {death_save_dc}."
                    ),
                    actor_kind=target.kind,
                    actor_source_id=target.source_id,
                    actor_name=target.name,
                )
            elif target_dead:
                self.repository.remove_combatant(
                    scene.id,
                    target.kind,
                    target.source_id,
                )
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_died",
                    (
                        f"{target.name} reached {target_hp} HP "
                        f"(-{character.max_hp} Max HP) and died instantly."
                    ),
                    actor_kind=target.kind,
                    actor_source_id=target.source_id,
                    actor_name=target.name,
                )
        except ValueError as error:
            raise CombatError(str(error)) from error

        return self._require_current(guild_id), result
