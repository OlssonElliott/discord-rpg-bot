"""Character presence, movement, and world action locking."""

from __future__ import annotations

from dataclasses import replace

from ...characters.models import Character
from ..dungeon import CharacterLocation, GameLock
from ..models import EntityKind, InvalidMovementError, MovementResult, Room


class WorldCharacterMixin:
    def get_character_room(self, character_id: int) -> Room | None:
        room = self.database.get_character_room(character_id)
        if room is None:
            return None
        visible_entities = tuple(
            entity
            for entity in room.entities
            if entity.kind is not EntityKind.CONTAINER
            or self.database.character_knows_container(character_id, entity.id)
        )
        return replace(room, entities=visible_entities)

    def get_character_location(self, character_id: int) -> CharacterLocation | None:
        return self.database.get_character_location(character_id)

    def list_characters(self) -> tuple[Character, ...]:
        return tuple(self.database.list_all_characters())

    def place_character(self, character_id: int, room_id: str) -> Room:
        return self.database.place_character(character_id, room_id)

    def move_character(self, character_id: int, destination: str) -> Room:
        return self.move_character_with_result(character_id, destination).room

    def move_character_with_result(
        self, character_id: int, destination: str
    ) -> MovementResult:
        if self.database.get_game_lock() in (
            GameLock.MOVEMENT_LOCKED,
            GameLock.ALL_ACTIONS_LOCKED,
        ):
            raise InvalidMovementError("Movement is currently locked by the DM.")
        return self.database.move_character_with_result(character_id, destination)

    def game_lock(self) -> GameLock:
        return self.database.get_game_lock()

    def set_game_lock(self, state: GameLock) -> GameLock:
        return self.database.set_game_lock(state)
