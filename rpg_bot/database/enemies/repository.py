"""Placed enemy instance persistence for the database facade."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from ...world import NotFoundError


class DatabaseEnemiesMixin:
    """Persist placed enemy instances."""

    def create_enemy_instance(
        self,
        room_id: str,
        template_id: str,
        *,
        instance_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ):
        template = self.get_enemy_template(template_id)
        if template is None:
            raise NotFoundError(
                f"Enemy template '{template_id}' does not exist."
            )

        clean_id = self._clean_identifier(
            instance_id or f"{template.template_id}_{uuid4().hex[:12]}",
            "Enemy ID",
        )
        clean_name = self._clean_name(
            name or template.name, "Enemy name"
        )
        resolved_description = (
            template.description if description is None else description
        )

        with self._connect() as connection:
            self._require_room(connection, room_id)
            try:
                connection.execute(
                    """
                    INSERT INTO world_entities (
                        id, room_id, kind, name, description
                    ) VALUES (?, ?, 'enemy', ?, ?)
                    """,
                    (
                        clean_id,
                        room_id,
                        clean_name,
                        resolved_description,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO world_enemies (
                        entity_id, template_id, current_hp, status
                    ) VALUES (?, ?, ?, 'active')
                    """,
                    (
                        clean_id,
                        template.template_id,
                        template.max_hp,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Enemy '{clean_id}' already exists."
                ) from error

        created = self.get_enemy_instance(clean_id)
        assert created is not None
        return created

    def get_enemy_instance(self, enemy_id: str):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT entity.id, entity.room_id, enemy.template_id,
                       entity.name, entity.description,
                       enemy.current_hp, enemy.status
                FROM world_entities AS entity
                JOIN world_enemies AS enemy
                  ON enemy.entity_id = entity.id
                WHERE entity.id = ? AND entity.kind = 'enemy'
                """,
                (enemy_id,),
            ).fetchone()

        return (
            self._enemy_instance_from_row(row)
            if row is not None
            else None
        )

    def list_room_enemy_instances(self, room_id: str):
        with self._connect() as connection:
            self._require_room(connection, room_id)
            rows = connection.execute(
                """
                SELECT entity.id, entity.room_id, enemy.template_id,
                       entity.name, entity.description,
                       enemy.current_hp, enemy.status
                FROM world_entities AS entity
                JOIN world_enemies AS enemy
                  ON enemy.entity_id = entity.id
                WHERE entity.room_id = ? AND entity.kind = 'enemy'
                ORDER BY entity.name COLLATE NOCASE, entity.id
                """,
                (room_id,),
            ).fetchall()

        return tuple(
            self._enemy_instance_from_row(row)
            for row in rows
        )

    def update_enemy_instance(self, enemy):
        template = self.get_enemy_template(enemy.template_id)
        if template is None:
            raise NotFoundError(
                f"Enemy template '{enemy.template_id}' does not exist."
            )

        if enemy.current_hp < 0 or enemy.current_hp > template.max_hp:
            raise ValueError(
                f"Enemy HP must be between 0 and {template.max_hp}."
            )

        clean_name = self._clean_name(enemy.name, "Enemy name")

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT 1 FROM world_entities
                WHERE id = ? AND kind = 'enemy'
                """,
                (enemy.id,),
            ).fetchone()

            if existing is None:
                raise NotFoundError(
                    f"Enemy '{enemy.id}' does not exist."
                )

            connection.execute(
                """
                UPDATE world_entities
                SET name = ?, description = ?
                WHERE id = ?
                """,
                (
                    clean_name,
                    enemy.description,
                    enemy.id,
                ),
            )
            connection.execute(
                """
                UPDATE world_enemies
                SET current_hp = ?, status = ?
                WHERE entity_id = ?
                """,
                (
                    enemy.current_hp,
                    enemy.status.value,
                    enemy.id,
                ),
            )

        updated = self.get_enemy_instance(enemy.id)
        assert updated is not None
        return updated

    @staticmethod
    def _enemy_instance_from_row(row):
        from ...world.enemies import EnemyInstance, EnemyStatus

        return EnemyInstance(
            id=row["id"],
            room_id=row["room_id"],
            template_id=row["template_id"],
            name=row["name"],
            current_hp=row["current_hp"],
            status=EnemyStatus(row["status"]),
            description=row["description"],
        )
