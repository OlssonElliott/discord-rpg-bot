"""World entity persistence for the database facade."""

from __future__ import annotations

import sqlite3

from ...world import EntityKind, NotFoundError, WorldEntity


class DatabaseWorldEntitiesMixin:
    """Persist generic world entities and their room placement."""

    def create_world_entity(
        self,
        entity_id: str,
        room_id: str,
        kind: EntityKind,
        name: str,
        description: str | None = None,
    ) -> WorldEntity:
        entity_id = self._clean_identifier(entity_id, "Entity ID")
        name = self._clean_name(name, "Entity name")
        with self._connect() as connection:
            self._require_room(connection, room_id)
            try:
                connection.execute(
                    """
                    INSERT INTO world_entities (id, room_id, kind, name, description)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (entity_id, room_id, kind.value, name, description),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"Entity '{entity_id}' already exists.") from error
        return WorldEntity(entity_id, room_id, kind, name, description)

    def move_world_entity(self, entity_id: str, room_id: str) -> WorldEntity:
        with self._connect() as connection:
            self._require_room(connection, room_id)
            cursor = connection.execute(
                "UPDATE world_entities SET room_id = ? WHERE id = ?",
                (room_id, entity_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(f"Entity '{entity_id}' does not exist.")
            row = connection.execute(
                "SELECT id, room_id, kind, name, description FROM world_entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
        return self._to_entity(row)

    def remove_world_entity(self, entity_id: str) -> None:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM world_entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if exists is None:
                raise NotFoundError(f"Entity '{entity_id}' does not exist.")
            connection.execute(
                "DELETE FROM inventory_stacks WHERE holder_kind = 'entity' AND holder_id = ?",
                (entity_id,),
            )
            connection.execute("DELETE FROM world_entities WHERE id = ?", (entity_id,))

    @staticmethod
    def _to_entity(row: sqlite3.Row) -> WorldEntity:
        return WorldEntity(
            row["id"],
            row["room_id"],
            EntityKind(row["kind"]),
            row["name"],
            row["description"],
        )
