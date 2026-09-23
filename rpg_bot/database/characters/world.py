"""Character placement and movement persistence."""

from __future__ import annotations

from ..errors import CharacterNotFoundError
from ...world.dungeon import (
    CharacterLocation,
    ConnectionType,
    TrapDamageType,
    TrapState,
)
from ...world import InvalidMovementError, MovementResult, Room


class DatabaseCharacterWorldMixin:
    """Persist character location and movement through the world."""

    def get_character_room(self, character_id: int) -> Room | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT current_room_id FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
            if row is None:
                raise CharacterNotFoundError("That character does not exist.")
            if row["current_room_id"] is None:
                return None
            room_row = connection.execute(
                """
                SELECT id, area_id, name, description, floor_id, width, height,
                       scene_image_path, scene_image_url, scene_prompt
                FROM rooms WHERE id = ?
                """,
                (row["current_room_id"],),
            ).fetchone()
            return self._to_room(connection, room_row) if room_row else None

    def place_character(self, character_id: int, room_id: str) -> Room:
        with self._connect() as connection:
            self._require_room(connection, room_id)
            previous = connection.execute(
                "SELECT current_room_id FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
            cursor = connection.execute(
                "UPDATE characters SET current_room_id = ? WHERE id = ? AND is_archived = 0",
                (room_id, character_id),
            )
            if cursor.rowcount == 0:
                raise CharacterNotFoundError("That character does not exist.")
            self._record_room_visit(connection, character_id, room_id)
            if previous is not None and previous["current_room_id"] is not None:
                self._queue_map_refresh_for_room(
                    connection, previous["current_room_id"]
                )
            self._queue_map_refresh_for_room(connection, room_id)
        room = self.get_room(room_id)
        assert room is not None
        return room

    def move_character(self, character_id: int, destination: str) -> Room:
        return self.move_character_with_result(character_id, destination).room

    def move_character_with_result(
        self, character_id: int, destination: str
    ) -> MovementResult:
        destination = destination.strip()
        trap_triggered = False
        trap_damage = 0
        trap_damage_type = None
        with self._connect() as connection:
            character = connection.execute(
                """
                SELECT current_room_id, hp, max_hp
                FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            current_room_id = character["current_room_id"]
            if current_room_id is None:
                raise InvalidMovementError("The character is not currently in a room.")
            exit_row = connection.execute(
                """
                SELECT name, destination_room_id FROM room_exits
                WHERE room_id = ? AND (name = ? COLLATE NOCASE OR destination_room_id = ?)
                """,
                (current_room_id, destination, destination),
            ).fetchone()
            if exit_row is None:
                raise InvalidMovementError(
                    f"'{destination}' is not an exit from the current room."
                )
            destination_id = exit_row["destination_room_id"]
            locked = connection.execute(
                """
                SELECT id, from_room_id, to_room_id,
                       is_locked, is_open, connection_type,
                       has_trap, trap_state, trap_damage_type,
                       trap_damage
                FROM room_connections
                WHERE (
                    from_room_id = ? AND exit_name = ? COLLATE NOCASE
                    AND to_room_id = ?
                ) OR (
                    to_room_id = ? AND return_exit_name = ? COLLATE NOCASE
                    AND from_room_id = ?
                )
                """,
                (
                    current_room_id,
                    exit_row["name"],
                    destination_id,
                    current_room_id,
                    exit_row["name"],
                    destination_id,
                ),
            ).fetchone()
            if locked is not None and locked["is_locked"]:
                raise InvalidMovementError("That door is locked.")
            self._require_room(connection, destination_id)
            if (
                locked is not None
                and locked["has_trap"]
                and locked["trap_state"] == TrapState.ARMED.value
            ):
                configured_damage = max(0, int(locked["trap_damage"] or 0))
                trap_triggered = True
                trap_damage_type = (
                    TrapDamageType(locked["trap_damage_type"])
                    if locked["trap_damage_type"]
                    else None
                )
                if configured_damage:
                    new_hp, _, _ = self._apply_character_damage(
                        connection,
                        character_id,
                        configured_damage,
                    )
                    trap_damage = int(character["hp"]) - new_hp
                connection.execute(
                    "UPDATE room_connections SET trap_state = ? WHERE id = ?",
                    (TrapState.TRIGGERED.value, locked["id"]),
                )
                self._queue_map_refresh_for_room(connection, locked["from_room_id"])
                self._queue_map_refresh_for_room(connection, locked["to_room_id"])
            if (
                locked is not None
                and ConnectionType(locked["connection_type"])
                is ConnectionType.DOOR
                and not locked["is_open"]
            ):
                connection.execute(
                    "UPDATE room_connections SET is_open = 1 WHERE id = ?",
                    (locked["id"],),
                )
                self._queue_map_refresh_for_room(connection, locked["from_room_id"])
                self._queue_map_refresh_for_room(connection, locked["to_room_id"])
            connection.execute(
                "UPDATE characters SET current_room_id = ? WHERE id = ?",
                (destination_id, character_id),
            )
            self._record_room_visit(connection, character_id, destination_id)
            self._queue_map_refresh_for_room(connection, current_room_id)
            self._queue_map_refresh_for_room(connection, destination_id)
        room = self.get_room(destination_id)
        assert room is not None
        return MovementResult(
            room=room,
            trap_triggered=trap_triggered,
            trap_damage=trap_damage,
            trap_damage_type=trap_damage_type,
        )

    def get_character_location(self, character_id: int) -> CharacterLocation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT current_room_id FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
        if row is None:
            raise CharacterNotFoundError("That character does not exist.")
        if row["current_room_id"] is None:
            return None
        return CharacterLocation(character_id, row["current_room_id"])

