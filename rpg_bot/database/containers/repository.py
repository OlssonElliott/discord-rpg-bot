"""Container instance persistence for the database facade."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from ..errors import CharacterNotFoundError
from ...world import NotFoundError


class DatabaseContainersMixin:
    """Persist placed containers and per-character discovery state."""

    def create_container_instance(
        self,
        room_id: str,
        template_id: str,
        *,
        instance_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        has_lock: bool | None = None,
        is_locked: bool | None = None,
        is_broken: bool | None = None,
        unlock_difficulty: int | None = None,
        hidden: bool | None = None,
        discovery_difficulty: int | None = None,
        is_open: bool = False,
        searched: bool = False,
    ):
        template = self.get_container_template(template_id)
        if template is None:
            raise NotFoundError(
                f"Container template '{template_id}' does not exist."
            )
        clean_id = self._clean_identifier(
            instance_id or f"{template.template_id}_{uuid4().hex[:12]}",
            "Container ID",
        )
        clean_name = self._clean_name(name or template.name, "Container name")
        resolved_has_lock = (
            template.default_has_lock if has_lock is None else has_lock
        )
        resolved_is_locked = (
            template.default_is_locked if is_locked is None else is_locked
        )
        resolved_is_broken = (
            template.default_is_broken if is_broken is None else is_broken
        )
        resolved_unlock_difficulty = (
            template.default_unlock_difficulty
            if unlock_difficulty is None and is_locked is None
            else unlock_difficulty
        )
        from ...world.locks import validate_lock

        resolved_unlock_difficulty = validate_lock(
            resolved_has_lock,
            resolved_is_locked,
            resolved_is_broken,
            resolved_unlock_difficulty,
            subject="container",
        )
        if is_open and resolved_is_locked:
            raise ValueError("A locked container cannot be open.")
        resolved_hidden = template.default_hidden if hidden is None else hidden
        resolved_discovery_difficulty = (
            template.default_discovery_difficulty
            if discovery_difficulty is None and hidden is None
            else discovery_difficulty
        )
        resolved_discovery_difficulty = self._validate_container_discovery(
            resolved_hidden,
            resolved_discovery_difficulty,
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
                    ) VALUES (?, ?, 'container', ?, ?)
                    """,
                    (clean_id, room_id, clean_name, resolved_description),
                )
                connection.execute(
                    """
                    INSERT INTO world_containers (
                        entity_id, template_id, has_lock, is_locked, is_broken,
                        unlock_difficulty, hidden, discovery_difficulty,
                        is_open, searched
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_id,
                        template.template_id,
                        int(resolved_has_lock),
                        int(resolved_is_locked),
                        int(resolved_is_broken),
                        resolved_unlock_difficulty,
                        int(resolved_hidden),
                        resolved_discovery_difficulty,
                        int(is_open),
                        int(searched),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"Container '{clean_id}' already exists.") from error
        created = self.get_container_instance(clean_id)
        assert created is not None
        return created

    def get_container_instance(self, container_id: str):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT entity.id, entity.room_id,
                       COALESCE(container.template_id, 'other') AS template_id,
                       entity.name,
                       COALESCE(template.container_type, 'other') AS container_type,
                       entity.description,
                       COALESCE(container.has_lock, 0) AS has_lock,
                       COALESCE(container.is_locked, 0) AS is_locked,
                       COALESCE(container.is_broken, 0) AS is_broken,
                       container.unlock_difficulty,
                       COALESCE(container.hidden, 0) AS hidden,
                       container.discovery_difficulty,
                       COALESCE(container.is_open, 0) AS is_open,
                       COALESCE(container.searched, 0) AS searched
                FROM world_entities AS entity
                LEFT JOIN world_containers AS container
                  ON container.entity_id = entity.id
                LEFT JOIN container_templates AS template
                  ON template.id = container.template_id
                WHERE entity.id = ? AND entity.kind = 'container'
                """,
                (container_id,),
            ).fetchone()
        return self._container_instance_from_row(row) if row is not None else None

    def list_room_container_instances(self, room_id: str):
        with self._connect() as connection:
            self._require_room(connection, room_id)
            rows = connection.execute(
                """
                SELECT entity.id, entity.room_id,
                       COALESCE(container.template_id, 'other') AS template_id,
                       entity.name,
                       COALESCE(template.container_type, 'other') AS container_type,
                       entity.description,
                       COALESCE(container.has_lock, 0) AS has_lock,
                       COALESCE(container.is_locked, 0) AS is_locked,
                       COALESCE(container.is_broken, 0) AS is_broken,
                       container.unlock_difficulty,
                       COALESCE(container.hidden, 0) AS hidden,
                       container.discovery_difficulty,
                       COALESCE(container.is_open, 0) AS is_open,
                       COALESCE(container.searched, 0) AS searched
                FROM world_entities AS entity
                LEFT JOIN world_containers AS container
                  ON container.entity_id = entity.id
                LEFT JOIN container_templates AS template
                  ON template.id = container.template_id
                WHERE entity.room_id = ? AND entity.kind = 'container'
                ORDER BY entity.name COLLATE NOCASE, entity.id
                """,
                (room_id,),
            ).fetchall()
        return tuple(self._container_instance_from_row(row) for row in rows)

    def update_container_instance(self, container):
        clean_name = self._clean_name(container.name, "Container name")
        from ...world.locks import validate_lock

        unlock_difficulty = validate_lock(
            container.has_lock,
            container.is_locked,
            container.is_broken,
            container.unlock_difficulty,
            subject="container",
        )
        if container.is_open and container.is_locked:
            raise ValueError("A locked container cannot be open.")
        discovery_difficulty = self._validate_container_discovery(
            container.hidden,
            container.discovery_difficulty,
        )
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT 1 FROM world_entities
                WHERE id = ? AND kind = 'container'
                """,
                (container.id,),
            ).fetchone()
            if existing is None:
                raise NotFoundError(
                    f"Container '{container.id}' does not exist."
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO world_containers (
                    entity_id, template_id, has_lock, is_locked, is_broken,
                    unlock_difficulty, hidden, discovery_difficulty,
                    is_open, searched
                ) VALUES (?, ?, 0, 0, 0, NULL, 0, NULL, 0, 0)
                """,
                (container.id, container.template_id),
            )
            connection.execute(
                """
                UPDATE world_entities
                SET name = ?, description = ?
                WHERE id = ?
                """,
                (clean_name, container.description, container.id),
            )
            connection.execute(
                """
                UPDATE world_containers
                SET template_id = ?, has_lock = ?, is_locked = ?,
                    is_broken = ?, unlock_difficulty = ?, hidden = ?,
                    discovery_difficulty = ?, is_open = ?, searched = ?
                WHERE entity_id = ?
                """,
                (
                    container.template_id,
                    int(container.has_lock),
                    int(container.is_locked),
                    int(container.is_broken),
                    unlock_difficulty,
                    int(container.hidden),
                    discovery_difficulty,
                    int(container.is_open),
                    int(container.searched),
                    container.id,
                ),
            )
        updated = self.get_container_instance(container.id)
        assert updated is not None
        return updated

    def remove_container_instance(self, container_id: str) -> None:
        with self._connect() as connection:
            exists = connection.execute(
                """
                SELECT 1 FROM world_entities
                WHERE id = ? AND kind = 'container'
                """,
                (container_id,),
            ).fetchone()
            if exists is None:
                raise NotFoundError(f"Container '{container_id}' does not exist.")
            connection.execute(
                "DELETE FROM character_known_containers WHERE container_id = ?",
                (container_id,),
            )
            connection.execute(
                """
                DELETE FROM inventory_stacks
                WHERE holder_kind = 'entity' AND holder_id = ?
                """,
                (container_id,),
            )
            connection.execute(
                "DELETE FROM world_containers WHERE entity_id = ?",
                (container_id,),
            )
            connection.execute(
                "DELETE FROM world_entities WHERE id = ?",
                (container_id,),
            )

    def character_knows_container(
        self,
        character_id: int,
        container_id: str,
    ) -> bool:
        container = self.get_container_instance(container_id)
        if container is None:
            raise NotFoundError(f"Container '{container_id}' does not exist.")
        if not container.hidden:
            return True
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT 1 FROM character_known_containers
                WHERE character_id = ? AND container_id = ?
                """,
                (character_id, container_id),
            ).fetchone() is not None

    def mark_container_discovered(
        self,
        character_id: int,
        container_id: str,
    ) -> None:
        with self._connect() as connection:
            character = connection.execute(
                """
                SELECT 1 FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            container = connection.execute(
                """
                SELECT 1 FROM world_entities
                WHERE id = ? AND kind = 'container'
                """,
                (container_id,),
            ).fetchone()
            if container is None:
                raise NotFoundError(
                    f"Container '{container_id}' does not exist."
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO character_known_containers (
                    character_id, container_id
                ) VALUES (?, ?)
                """,
                (character_id, container_id),
            )

    @staticmethod
    def _validate_container_discovery(
        hidden: bool,
        discovery_difficulty: int | None,
    ) -> int | None:
        if not hidden:
            return None
        if (
            isinstance(discovery_difficulty, bool)
            or not isinstance(discovery_difficulty, int)
            or not 1 <= discovery_difficulty <= 30
        ):
            raise ValueError(
                "Discovery difficulty must be an integer from 1 to 30."
            )
        return discovery_difficulty

    @staticmethod
    def _container_instance_from_row(row):
        from ...world.containers import ContainerInstance, ContainerType

        return ContainerInstance(
            row["id"],
            row["room_id"],
            row["template_id"],
            row["name"],
            ContainerType(row["container_type"]),
            row["description"],
            bool(row["has_lock"]),
            bool(row["is_locked"]),
            bool(row["is_broken"]),
            row["unlock_difficulty"],
            bool(row["hidden"]),
            row["discovery_difficulty"],
            bool(row["is_open"]),
            bool(row["searched"]),
        )
