"""Container template persistence for the database facade."""

from __future__ import annotations

import sqlite3

from ...world import NotFoundError


class DatabaseContainerTemplatesMixin:
    """Persist reusable container templates."""

    def list_container_templates(self):
        from ...world.containers import ContainerTemplate, ContainerType

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, container_type, description,
                       default_has_lock, default_is_locked, default_is_broken,
                       default_unlock_difficulty, default_hidden,
                       default_discovery_difficulty
                FROM container_templates
                ORDER BY name COLLATE NOCASE, id
                """
            ).fetchall()
        return tuple(
            ContainerTemplate(
                row["id"],
                row["name"],
                ContainerType(row["container_type"]),
                row["description"],
                bool(row["default_has_lock"]),
                bool(row["default_is_locked"]),
                bool(row["default_is_broken"]),
                row["default_unlock_difficulty"],
                bool(row["default_hidden"]),
                row["default_discovery_difficulty"],
            )
            for row in rows
        )

    def get_container_template(self, template_id: str):
        from ...world.containers import ContainerTemplate, ContainerType

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, container_type, description,
                       default_has_lock, default_is_locked, default_is_broken,
                       default_unlock_difficulty, default_hidden,
                       default_discovery_difficulty
                FROM container_templates WHERE id = ?
                """,
                (template_id,),
            ).fetchone()
        if row is None:
            return None
        return ContainerTemplate(
            row["id"],
            row["name"],
            ContainerType(row["container_type"]),
            row["description"],
            bool(row["default_has_lock"]),
            bool(row["default_is_locked"]),
            bool(row["default_is_broken"]),
            row["default_unlock_difficulty"],
            bool(row["default_hidden"]),
            row["default_discovery_difficulty"],
        )

    def create_container_template(self, template):
        template_id = self._clean_identifier(template.template_id, "Container template ID")
        name = self._clean_name(template.name, "Container name")
        from ...world.locks import validate_lock

        unlock_difficulty = validate_lock(
            template.default_has_lock,
            template.default_is_locked,
            template.default_is_broken,
            template.default_unlock_difficulty,
            subject="container",
        )
        discovery_difficulty = self._validate_container_discovery(
            template.default_hidden,
            template.default_discovery_difficulty,
        )
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO container_templates (
                        id, name, container_type, description,
                        default_has_lock, default_is_locked, default_is_broken,
                        default_unlock_difficulty, default_hidden,
                        default_discovery_difficulty
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        template_id,
                        name,
                        template.container_type.value,
                        template.description,
                        int(template.default_has_lock),
                        int(template.default_is_locked),
                        int(template.default_is_broken),
                        unlock_difficulty,
                        int(template.default_hidden),
                        discovery_difficulty,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Container template '{template_id}' already exists."
                ) from error
        created = self.get_container_template(template_id)
        assert created is not None
        return created

    def update_container_template(self, template_id: str, template):
        clean_id = self._clean_identifier(template_id, "Container template ID")
        name = self._clean_name(template.name, "Container name")
        from ...world.locks import validate_lock

        unlock_difficulty = validate_lock(
            template.default_has_lock,
            template.default_is_locked,
            template.default_is_broken,
            template.default_unlock_difficulty,
            subject="container",
        )
        discovery_difficulty = self._validate_container_discovery(
            template.default_hidden,
            template.default_discovery_difficulty,
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE container_templates
                SET name = ?, container_type = ?, description = ?,
                    default_has_lock = ?, default_is_locked = ?,
                    default_is_broken = ?, default_unlock_difficulty = ?,
                    default_hidden = ?, default_discovery_difficulty = ?
                WHERE id = ?
                """,
                (
                    name,
                    template.container_type.value,
                    template.description,
                    int(template.default_has_lock),
                    int(template.default_is_locked),
                    int(template.default_is_broken),
                    unlock_difficulty,
                    int(template.default_hidden),
                    discovery_difficulty,
                    clean_id,
                ),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Container template '{clean_id}' does not exist."
                )
        updated = self.get_container_template(clean_id)
        assert updated is not None
        return updated
