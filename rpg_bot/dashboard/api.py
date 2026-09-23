"""Framework-neutral JSON API for the local DM dashboard."""

from pathlib import Path
from typing import Any

from ..combat.service import CombatService
from .routes.characters import handle_character_request
from .routes.combat import handle_combat_request
from .routes.connections import handle_connection_request
from .routes.containers import handle_container_request
from .routes.room_content import handle_room_content_request
from .serializers.common import _character_admin_data, _room_image_data
from .routes.templates import handle_template_request
from .routes.world import handle_world_request
from ..media.portraits import CharacterPortraitStore, InvalidPortraitError
from ..media.room_images import InvalidRoomImageError, RoomImageStore
from ..world import WorldError
from ..world.service import WorldService


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


class DashboardAPI:
    """Translate HTTP-shaped requests into deterministic service calls."""

    def __init__(
        self,
        world: WorldService,
        room_images: RoomImageStore | None = None,
        *,
        portraits: CharacterPortraitStore | None = None,
        combat: CombatService | None = None,
        guild_id: int | None = None,
    ) -> None:
        self.world = world
        self.room_images = room_images or RoomImageStore()
        self.portraits = portraits or CharacterPortraitStore()
        self.combat = combat or CombatService(world.database)
        self.guild_id = guild_id
        self._connection_trap_damage: dict[tuple[str, str], int] = {}

    def upload_room_image(
        self,
        room_id: str,
        content: bytes,
        content_type: str,
        original_filename: str | None = None,
    ) -> ApiResponse:
        """Validate, persist, and atomically associate a room image."""
        room = self.world.get_room(room_id)
        if room is None:
            return 404, {"error": f"Room '{room_id}' does not exist."}
        try:
            new_key = self.room_images.save(
                content, content_type, original_filename
            )
            try:
                updated = self.world.set_room_scene_image(room_id, new_key)
            except Exception:
                self.room_images.remove(new_key)
                raise
            self.room_images.remove(room.scene_image_path)
            return 200, _room_image_data(updated, self.room_images)
        except (InvalidRoomImageError, ValueError, WorldError) as error:
            return 400, {"error": str(error)}

    def room_image_path(self, room_id: str) -> Path | None:
        room = self.world.get_room(room_id)
        if room is None:
            return None
        return self.room_images.path_for(room.scene_image_path)

    def character_portrait_path(self, character_id: int) -> Path | None:
        character = self.world.database.get_character_by_global_id(character_id)
        if character is None:
            return None
        return self.portraits.path_for(character.portrait_key)

    def upload_character_portrait(
        self,
        character_id: int,
        content: bytes,
    ) -> ApiResponse:
        character = self.world.database.get_character_by_global_id(character_id)
        if character is None:
            return 404, {"error": f"Character {character_id} does not exist."}
        try:
            new_key = self.portraits.save(character_id, content)
            try:
                updated = self.world.database.set_character_portrait(
                    character.discord_user_id,
                    character_id,
                    new_key,
                )
            except Exception:
                self.portraits.remove(new_key)
                raise
            self.portraits.remove(character.portrait_key)
            return 200, _character_admin_data(
                self.world,
                self.portraits,
                updated,
            )
        except (InvalidPortraitError, ValueError, WorldError) as error:
            return 400, {"error": str(error)}

    def handle(
        self,
        method: str,
        path: str,
        body: JsonObject | None = None,
    ) -> ApiResponse:
        body = body or {}
        try:
            return self._handle(method.upper(), path.rstrip("/") or "/", body)
        except (ValueError, WorldError) as error:
            return 400, {"error": str(error)}

    def _handle(self, method: str, path: str, body: JsonObject) -> ApiResponse:
        response = handle_combat_request(self, method, path, body)
        if response is not None:
            return response

        response = handle_character_request(self, method, path, body)
        if response is not None:
            return response

        response = handle_template_request(self, method, path, body)
        if response is not None:
            return response

        response = handle_world_request(self, method, path, body)
        if response is not None:
            return response

        response = handle_container_request(self, method, path, body)
        if response is not None:
            return response

        response = handle_room_content_request(self, method, path, body)
        if response is not None:
            return response

        response = handle_connection_request(self, method, path, body)
        if response is not None:
            return response

        return 404, {"error": "Not found."}

