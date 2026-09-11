"""Build filtered dungeon views and maintain their persistent message state."""

from collections.abc import Iterable

from .database import Database
from .dungeon import (
    CharacterRoomKnowledge,
    FocusedRoomView,
    KnowledgeState,
    PerceptionModifier,
    PlayerMap,
    PlayerMapConnection,
    PlayerMapRoom,
    PlayerViewMessageAdapter,
    PlayerViewState,
)
from .world import NotFoundError


class PlayerViewService:
    """Application service implementing world -> knowledge -> effects -> view."""

    def __init__(
        self,
        database: Database,
        perception_modifiers: Iterable[PerceptionModifier] = (),
    ) -> None:
        self.database = database
        self.perception_modifiers = tuple(perception_modifiers)

    def share_room_knowledge(
        self, from_character_id: int, to_character_id: int, room_id: str
    ) -> CharacterRoomKnowledge:
        return self.database.share_room_knowledge(
            from_character_id, to_character_id, room_id
        )

    def focus_room(self, character_id: int, room_id: str) -> PlayerViewState:
        knowledge = self.database.get_character_knowledge(character_id, room_id)
        if knowledge is None:
            raise ValueError("A character can only focus a room they know about.")
        room = self.database.get_room(room_id)
        if room is None or room.floor_id is None:
            raise NotFoundError(f"Room '{room_id}' has no dungeon floor.")
        return self.database.update_player_view_state(
            character_id,
            selected_floor_id=room.floor_id,
            focused_room_id=room_id,
        )

    def select_floor(self, character_id: int, floor_id: str) -> PlayerViewState:
        floor = self.database.get_floor(floor_id)
        if floor is None:
            raise NotFoundError(f"Floor '{floor_id}' does not exist.")
        return self.database.update_player_view_state(
            character_id, selected_floor_id=floor_id
        )

    def bind_discord_channel(
        self, character_id: int, channel_id: int
    ) -> PlayerViewState:
        current = self.database.get_player_view_state(character_id)
        if current.discord_channel_id == channel_id:
            return current
        return self.database.bind_player_view_channel(character_id, channel_id)

    def build_player_map(
        self, character_id: int, floor_id: str | None = None
    ) -> PlayerMap:
        state = self.database.get_player_view_state(character_id)
        chosen_floor_id = floor_id or state.selected_floor_id
        if chosen_floor_id is None:
            raise ValueError("The player view has no selected dungeon floor.")
        floor = self.database.get_floor(chosen_floor_id)
        if floor is None:
            raise NotFoundError(f"Floor '{chosen_floor_id}' does not exist.")

        character = next(
            (
                item
                for item in self.database.list_all_characters()
                if item.character_id == character_id
            ),
            None,
        )
        if character is None:
            raise ValueError("That character does not exist.")
        knowledge_rows = self.database.list_character_knowledge(
            character_id, floor_id=chosen_floor_id
        )
        rooms = []
        knowledge_by_room = {knowledge.room_id: knowledge for knowledge in knowledge_rows}
        for knowledge in knowledge_rows:
            room = self.database.get_room(knowledge.room_id)
            if room is None:
                continue
            rooms.append(
                PlayerMapRoom(
                    room.id,
                    room.floor_id or chosen_floor_id,
                    room.name,
                    room.x,
                    room.y,
                    room.width,
                    room.height,
                    knowledge.state,
                    room.id == character.current_room_id,
                    room.id == state.focused_room_id,
                    (
                        (character.name,)
                        + tuple(
                            occupant.name
                            for occupant in room.characters
                            if occupant.character_id != character_id
                        )
                        if room.id == character.current_room_id
                        else ()
                    ),
                )
            )

        connections = []
        for connection in self.database.list_known_connections(character_id):
            source = self.database.get_room(connection.from_room_id)
            target = self.database.get_room(connection.to_room_id)
            if source is None or target is None:
                continue
            if chosen_floor_id not in (source.floor_id, target.floor_id):
                continue
            connections.append(
                PlayerMapConnection(
                    connection.id,
                    connection.from_room_id,
                    connection.to_room_id,
                    source.floor_id or "",
                    target.floor_id or "",
                    connection.connection_type,
                    connection.bidirectional,
                )
            )

        focused = self._focused_room(
            character_id,
            character.current_room_id,
            state.focused_room_id,
            knowledge_by_room,
        )
        view = PlayerMap(
            character_id,
            floor.dungeon_id,
            floor,
            character.current_room_id,
            state.focused_room_id,
            tuple(rooms),
            tuple(connections),
            focused,
        )
        for modifier in self.perception_modifiers:
            view = modifier.apply(view)
        return view

    def _focused_room(
        self,
        character_id: int,
        current_room_id: str | None,
        focused_room_id: str | None,
        floor_knowledge: dict,
    ) -> FocusedRoomView | None:
        if focused_room_id is None:
            return None
        knowledge = floor_knowledge.get(focused_room_id)
        if knowledge is None:
            return None
        room = self.database.get_room(focused_room_id)
        if room is None:
            return None
        if knowledge.state is KnowledgeState.KNOWN:
            return FocusedRoomView(room.id, knowledge.state, room.name)

        visible_characters: tuple[str, ...] = ()
        visible_entities: tuple[str, ...] = ()
        visible_items: tuple[str, ...] = ()
        # Old visited rooms retain their scene asset and description, but live
        # occupants are only visible where the character physically is.
        if focused_room_id == current_room_id:
            visible_characters = tuple(
                item.name
                for item in room.characters
                if item.character_id != character_id
            )
            visible_entities = tuple(item.name for item in room.entities)
            visible_items = tuple(
                (
                    item.item.name
                    if item.quantity == 1
                    else f"{item.item.name} x{item.quantity}"
                )
                for item in room.loose_items
            )
        return FocusedRoomView(
            room.id,
            knowledge.state,
            room.name,
            room.description,
            room.scene_image_path,
            room.scene_image_url,
            visible_characters,
            visible_entities,
            visible_items,
        )


class PlayerViewMessageService:
    """Edit the bot-owned HUD message, recreating it when it was deleted."""

    def __init__(
        self,
        views: PlayerViewService,
        adapter: PlayerViewMessageAdapter,
    ) -> None:
        self.views = views
        self.adapter = adapter

    async def refresh(self, character_id: int) -> int:
        state = self.views.database.get_player_view_state(character_id)
        if state.discord_channel_id is None:
            raise ValueError("The player does not have a private view channel yet.")
        view = self.views.build_player_map(character_id)
        if state.discord_message_id is not None:
            edited = await self.adapter.edit_view_message(
                state.discord_channel_id, state.discord_message_id, view
            )
            if edited:
                return state.discord_message_id
        message_id = await self.adapter.create_view_message(
            state.discord_channel_id, view
        )
        self.views.database.update_player_view_state(
            character_id, discord_message_id=message_id
        )
        return message_id
