"""Enemy template persistence for the database facade."""

from __future__ import annotations

import sqlite3

from ...world import NotFoundError


class DatabaseEnemyTemplatesMixin:
    """Persist reusable enemy templates."""

    def list_enemy_templates(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, description, race, difficulty_level,
                       strength, dexterity, arcana, vitality, insight, personality,
                       max_hp, armor, magical_resistance, attack_dc, defense_dc,
                       damage, attack_profile, special_ability, typical_behaviour,
                       main_hand_item_id, off_hand_item_id, armor_item_id
                FROM enemy_templates
                ORDER BY name COLLATE NOCASE, id
                """
            ).fetchall()
        return tuple(self._enemy_template_from_row(row) for row in rows)

    def get_enemy_template(self, template_id: str):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, description, race, difficulty_level,
                       strength, dexterity, arcana, vitality, insight, personality,
                       max_hp, armor, magical_resistance, attack_dc, defense_dc,
                       damage, attack_profile, special_ability, typical_behaviour,
                       main_hand_item_id, off_hand_item_id, armor_item_id
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
                        id, name, description, race, difficulty_level,
                        strength, dexterity, arcana, vitality, insight, personality,
                        max_hp, armor, magical_resistance, attack_dc, defense_dc,
                        damage, attack_profile, special_ability, typical_behaviour,
                        main_hand_item_id, off_hand_item_id, armor_item_id
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        clean_id,
                        clean_name,
                        template.description,
                        template.race,
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
                SET name = ?, description = ?, race = ?, difficulty_level = ?,
                    strength = ?, dexterity = ?, arcana = ?, vitality = ?,
                    insight = ?, personality = ?, max_hp = ?, armor = ?,
                    magical_resistance = ?, attack_dc = ?, defense_dc = ?,
                    damage = ?, attack_profile = ?, special_ability = ?,
                    typical_behaviour = ?, main_hand_item_id = ?,
                    off_hand_item_id = ?, armor_item_id = ?
                WHERE id = ?
                """,
                (
                    clean_name,
                    template.description,
                    template.race,
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
        from ...world.enemies import EnemyTemplate

        return EnemyTemplate(
            template_id=row["id"],
            name=row["name"],
            description=row["description"],
            race=row["race"],
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
        )
