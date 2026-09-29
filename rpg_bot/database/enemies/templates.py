"""Enemy template persistence for the database facade."""

from __future__ import annotations

import json
import sqlite3

from ...world import NotFoundError


class DatabaseEnemyTemplatesMixin:
    """Persist reusable enemy templates."""

    def list_enemy_templates(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, description, race, lineage, difficulty_level,
                       strength, dexterity, arcana, vitality, insight, personality,
                       max_hp, armor, magical_resistance, attack_dc, defense_dc,
                       damage, attack_profile, special_ability, typical_behaviour,
                       main_hand_item_id, off_hand_item_id, armor_item_id,
                       melee_weapon_ids, ranged_weapon_ids, off_hand_item_ids,
                       armor_item_ids, spell_names, spell_range,
                       melee_damage_filter, ranged_damage_filter, natural_attacks,
                       armor_reduction_filter, dual_wield
                FROM enemy_templates
                ORDER BY name COLLATE NOCASE, id
                """
            ).fetchall()
        return tuple(self._enemy_template_from_row(row) for row in rows)

    def get_enemy_template(self, template_id: str):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, description, race, lineage, difficulty_level,
                       strength, dexterity, arcana, vitality, insight, personality,
                       max_hp, armor, magical_resistance, attack_dc, defense_dc,
                       damage, attack_profile, special_ability, typical_behaviour,
                       main_hand_item_id, off_hand_item_id, armor_item_id,
                       melee_weapon_ids, ranged_weapon_ids, off_hand_item_ids,
                       armor_item_ids, spell_names, spell_range,
                       melee_damage_filter, ranged_damage_filter, natural_attacks,
                       armor_reduction_filter, dual_wield
                FROM enemy_templates
                WHERE id = ?
                """,
                (template_id,),
            ).fetchone()
        return self._enemy_template_from_row(row) if row is not None else None

    def create_enemy_template(self, template):
        clean_id = self._clean_identifier(
            template.template_id, "Enemy template ID"
        )
        clean_name = self._clean_name(
            template.name, "Enemy template name"
        )
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO enemy_templates (
                        id, name, description, race, lineage, difficulty_level,
                        strength, dexterity, arcana, vitality, insight, personality,
                        max_hp, armor, magical_resistance, attack_dc, defense_dc,
                        damage, attack_profile, special_ability, typical_behaviour,
                        main_hand_item_id, off_hand_item_id, armor_item_id,
                        melee_weapon_ids, ranged_weapon_ids, off_hand_item_ids,
                        armor_item_ids, spell_names, spell_range,
                        melee_damage_filter, ranged_damage_filter, natural_attacks,
                        armor_reduction_filter, dual_wield
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        clean_id,
                        clean_name,
                        template.description,
                        template.race,
                        template.lineage,
                        template.difficulty_level,
                        template.strength,
                        template.dexterity,
                        template.arcana,
                        template.vitality,
                        template.insight,
                        template.personality,
                        template.max_hp,
                        template.armor,
                        template.magical_resistance,
                        template.attack_dc,
                        template.defense_dc,
                        template.damage,
                        template.attack_profile,
                        template.special_ability,
                        template.typical_behaviour,
                        template.main_hand_item_id,
                        template.off_hand_item_id,
                        template.armor_item_id,
                        json.dumps(template.melee_weapon_ids),
                        json.dumps(template.ranged_weapon_ids),
                        json.dumps(template.off_hand_item_ids),
                        json.dumps(template.armor_item_ids),
                        json.dumps(template.spell_names),
                        template.spell_range,
                        template.melee_damage_filter,
                        template.ranged_damage_filter,
                        json.dumps([
                            {
                                "name": attack.name,
                                "damage": attack.damage,
                                "damage_type": attack.damage_type,
                                "range": attack.range,
                            }
                            for attack in template.natural_attacks
                        ]),
                        template.armor_reduction_filter,
                        int(template.dual_wield),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Enemy template '{clean_id}' already exists."
                ) from error

        created = self.get_enemy_template(clean_id)
        assert created is not None
        return created

    def update_enemy_template(self, template_id: str, template):
        clean_id = self._clean_identifier(
            template_id, "Enemy template ID"
        )
        clean_name = self._clean_name(
            template.name, "Enemy template name"
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE enemy_templates
                SET name = ?, description = ?, race = ?, lineage = ?, difficulty_level = ?,
                    strength = ?, dexterity = ?, arcana = ?, vitality = ?,
                    insight = ?, personality = ?, max_hp = ?, armor = ?,
                    magical_resistance = ?, attack_dc = ?, defense_dc = ?,
                    damage = ?, attack_profile = ?, special_ability = ?,
                    typical_behaviour = ?, main_hand_item_id = ?,
                    off_hand_item_id = ?, armor_item_id = ?,
                    melee_weapon_ids = ?, ranged_weapon_ids = ?,
                    off_hand_item_ids = ?, armor_item_ids = ?,
                    spell_names = ?, spell_range = ?,
                    melee_damage_filter = ?, ranged_damage_filter = ?,
                    natural_attacks = ?, armor_reduction_filter = ?,
                    dual_wield = ?
                WHERE id = ?
                """,
                (
                    clean_name,
                    template.description,
                    template.race,
                    template.lineage,
                    template.difficulty_level,
                    template.strength,
                    template.dexterity,
                    template.arcana,
                    template.vitality,
                    template.insight,
                    template.personality,
                    template.max_hp,
                    template.armor,
                    template.magical_resistance,
                    template.attack_dc,
                    template.defense_dc,
                    template.damage,
                    template.attack_profile,
                    template.special_ability,
                    template.typical_behaviour,
                    template.main_hand_item_id,
                    template.off_hand_item_id,
                    template.armor_item_id,
                    json.dumps(template.melee_weapon_ids),
                    json.dumps(template.ranged_weapon_ids),
                    json.dumps(template.off_hand_item_ids),
                    json.dumps(template.armor_item_ids),
                    json.dumps(template.spell_names),
                    template.spell_range,
                    template.melee_damage_filter,
                    template.ranged_damage_filter,
                    json.dumps([
                        {
                            "name": attack.name,
                            "damage": attack.damage,
                            "damage_type": attack.damage_type,
                            "range": attack.range,
                        }
                        for attack in template.natural_attacks
                    ]),
                    template.armor_reduction_filter,
                    int(template.dual_wield),
                    clean_id,
                ),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Enemy template '{clean_id}' does not exist."
                )

            connection.execute(
                """
                UPDATE world_enemies
                SET current_hp = MIN(current_hp, ?)
                WHERE template_id = ?
                """,
                (template.max_hp, clean_id),
            )

        updated = self.get_enemy_template(clean_id)
        assert updated is not None
        return updated

    def remove_enemy_template(self, template_id: str) -> None:
        clean_id = self._clean_identifier(
            template_id, "Enemy template ID"
        )
        with self._connect() as connection:
            try:
                cursor = connection.execute(
                    "DELETE FROM enemy_templates WHERE id = ?",
                    (clean_id,),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "Enemy templates cannot be removed while placed "
                    "enemies use them."
                ) from error

            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Enemy template '{clean_id}' does not exist."
                )

    @staticmethod
    def _enemy_template_from_row(row):
        from ...world.enemies import EnemyNaturalAttack, EnemyTemplate

        return EnemyTemplate(
            template_id=row["id"],
            name=row["name"],
            description=row["description"],
            race=row["race"],
            lineage=row["lineage"],
            difficulty_level=row["difficulty_level"],
            strength=row["strength"],
            dexterity=row["dexterity"],
            arcana=row["arcana"],
            vitality=row["vitality"],
            insight=row["insight"],
            personality=row["personality"],
            max_hp=row["max_hp"],
            armor=row["armor"],
            magical_resistance=row["magical_resistance"],
            attack_dc=row["attack_dc"],
            defense_dc=row["defense_dc"],
            damage=row["damage"],
            attack_profile=row["attack_profile"],
            special_ability=row["special_ability"],
            typical_behaviour=row["typical_behaviour"],
            main_hand_item_id=row["main_hand_item_id"],
            off_hand_item_id=row["off_hand_item_id"],
            armor_item_id=row["armor_item_id"],
            melee_weapon_ids=tuple(json.loads(row["melee_weapon_ids"] or "[]")),
            ranged_weapon_ids=tuple(json.loads(row["ranged_weapon_ids"] or "[]")),
            off_hand_item_ids=tuple(json.loads(row["off_hand_item_ids"] or "[]")),
            armor_item_ids=tuple(json.loads(row["armor_item_ids"] or "[]")),
            spell_names=tuple(json.loads(row["spell_names"] or "[]")),
            spell_range=row["spell_range"],
            melee_damage_filter=row["melee_damage_filter"],
            ranged_damage_filter=row["ranged_damage_filter"],
            natural_attacks=tuple(
                EnemyNaturalAttack(
                    name=record["name"],
                    damage=record["damage"],
                    damage_type=record.get("damage_type", "physical"),
                    range=int(record.get("range", 0)),
                )
                for record in json.loads(row["natural_attacks"] or "[]")
            ),
            armor_reduction_filter=row["armor_reduction_filter"],
            dual_wield=bool(row["dual_wield"]),
        )
