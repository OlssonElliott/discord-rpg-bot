"""Deterministic application service for world state and item transfers."""

from .database import Database
from .inventory import (
    DEFAULT_ITEM_CATALOG_PATH,
    InventoryState,
    ItemCatalog,
    ItemInstance,
    ItemTemplate,
)
from .models import Character
from .world import (
    Area,
    AreaGraph,
    EntityKind,
    InvalidTransferError,
    InventoryHolder,
    Item,
    ItemStack,
    Room,
    WorldEntity,
)


class WorldService:
    """UI-independent entry point for all world mutations."""

    def __init__(self, database: Database, catalog: ItemCatalog | None = None) -> None:
        self.database = database
        self.catalog = catalog or ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)

    def create_area(
        self, area_id: str, name: str, description: str | None = None
    ) -> Area:
        return self.database.create_area(area_id, name, description)

    def create_room(
        self,
        room_id: str,
        area_id: str,
        name: str,
        description: str | None = None,
        *,
        editor_x: float | None = None,
        editor_y: float | None = None,
    ) -> Room:
        room = self.database.create_room(room_id, area_id, name, description)
        if editor_x is not None or editor_y is not None:
            if editor_x is None or editor_y is None:
                self.database.delete_room(room.id)
                raise ValueError("Both editor coordinates are required together.")
            self.database.set_room_editor_position(room.id, editor_x, editor_y)
        return room

    def list_areas(self) -> tuple[Area, ...]:
        return self.database.list_areas()

    def area_graph(self, area_id: str) -> AreaGraph:
        return self.database.get_area_graph(area_id)

    def update_room(
        self, room_id: str, name: str, description: str | None = None
    ) -> Room:
        return self.database.update_room(room_id, name, description)

    def delete_room(self, room_id: str) -> None:
        self.database.delete_room(room_id)

    def set_room_editor_position(self, room_id: str, x: float, y: float) -> None:
        self.database.set_room_editor_position(room_id, x, y)

    def connect_rooms(
        self,
        room_id: str,
        exit_name: str,
        destination_room_id: str,
        *,
        return_exit_name: str | None = None,
    ) -> None:
        self.database.connect_rooms(
            room_id,
            exit_name,
            destination_room_id,
            return_exit_name=return_exit_name,
        )

    def disconnect_rooms(self, room_id: str, exit_name: str) -> None:
        self.database.disconnect_rooms(room_id, exit_name)

    def get_room(self, room_id: str) -> Room | None:
        return self.database.get_room(room_id)

    def get_character_room(self, character_id: int) -> Room | None:
        return self.database.get_character_room(character_id)

    def list_characters(self) -> tuple[Character, ...]:
        return tuple(self.database.list_all_characters())

    def place_character(self, character_id: int, room_id: str) -> Room:
        return self.database.place_character(character_id, room_id)

    def move_character(self, character_id: int, destination: str) -> Room:
        return self.database.move_character(character_id, destination)

    def create_item(
        self,
        item_id: str,
        name: str,
        description: str | None = None,
        *,
        stackable: bool = True,
    ) -> Item:
        return self.database.create_item(
            item_id, name, description, stackable=stackable
        )

    def create_entity(
        self,
        entity_id: str,
        room_id: str,
        kind: EntityKind,
        name: str,
        description: str | None = None,
    ) -> WorldEntity:
        return self.database.create_world_entity(
            entity_id, room_id, kind, name, description
        )

    def move_entity(self, entity_id: str, room_id: str) -> WorldEntity:
        return self.database.move_world_entity(entity_id, room_id)

    def remove_entity(self, entity_id: str) -> None:
        self.database.remove_world_entity(entity_id)

    def place_item(
        self, holder: InventoryHolder, item_id: str, quantity: int = 1
    ) -> ItemStack:
        return self.database.add_item(holder, item_id, quantity)

    def inventory(self, holder: InventoryHolder) -> tuple[ItemStack, ...]:
        return self.database.get_inventory(holder)

    def transfer_item(
        self,
        source: InventoryHolder,
        destination: InventoryHolder,
        item: str,
        quantity: int = 1,
    ) -> ItemStack:
        """Atomically resolve and transfer an item ID or unambiguous name."""
        return self.database.transfer_item(source, destination, item, quantity)

    def take_loose_item(
        self, character_id: int, item: str, quantity: int = 1
    ) -> ItemStack:
        room = self.database.get_character_room(character_id)
        if room is None:
            raise InvalidTransferError("The character is not currently in a room.")
        source = InventoryHolder.room(room.id)
        template = self._catalog_template(source, item)
        if template is None:
            return self.transfer_item(
                source, InventoryHolder.character(character_id), item, quantity
            )
        self._validate_character_capacity(character_id, template, quantity)
        return self.database.take_world_item_into_character_inventory(
            source,
            character_id,
            item,
            template.template_id,
            quantity=quantity,
            durability=template.durability,
            stackable=template.stackable,
        )

    def drop_item(
        self, character_id: int, item: str, quantity: int = 1
    ) -> ItemStack:
        room = self.database.get_character_room(character_id)
        if room is None:
            raise InvalidTransferError("The character is not currently in a room.")
        inventory = self.database.get_character_inventory(character_id)
        try:
            selected = self._resolve_character_item(inventory, item)
        except InvalidTransferError:
            return self.transfer_item(
                InventoryHolder.character(character_id),
                InventoryHolder.room(room.id),
                item,
                quantity,
            )
        template = self.catalog.get(selected.template_id)
        world_item = Item(
            template.template_id,
            template.name,
            template.description,
            template.stackable,
        )
        return self.database.drop_character_inventory_item(
            character_id,
            selected.instance_id,
            InventoryHolder.room(room.id),
            world_item,
            quantity=quantity,
        )

    def take_from_container(
        self,
        character_id: int,
        container: str,
        item: str,
        quantity: int = 1,
    ) -> ItemStack:
        room = self.database.get_character_room(character_id)
        if room is None:
            raise InvalidTransferError("The character is not currently in a room.")
        matches = [
            entity
            for entity in room.containers
            if entity.id == container or entity.name.casefold() == container.casefold()
        ]
        if not matches:
            raise InvalidTransferError(f"There is no container named '{container}' here.")
        exact = [entity for entity in matches if entity.id == container]
        if not exact and len(matches) > 1:
            raise InvalidTransferError(
                f"More than one container is named '{container}'; use its ID."
            )
        selected = exact[0] if exact else matches[0]
        source = InventoryHolder.entity(selected.id)
        template = self._catalog_template(source, item)
        if template is None:
            return self.transfer_item(
                source, InventoryHolder.character(character_id), item, quantity
            )
        self._validate_character_capacity(character_id, template, quantity)
        return self.database.take_world_item_into_character_inventory(
            source,
            character_id,
            item,
            template.template_id,
            quantity=quantity,
            durability=template.durability,
            stackable=template.stackable,
        )

    def _catalog_template(
        self, holder: InventoryHolder, item_query: str
    ) -> ItemTemplate | None:
        stacks = self.database.get_inventory(holder)
        exact = [stack for stack in stacks if stack.item.id == item_query]
        matches = exact or [
            stack for stack in stacks
            if stack.item.name.casefold() == item_query.casefold()
        ]
        if len(matches) != 1:
            return None
        world_item = matches[0].item
        try:
            return self.catalog.get(world_item.id)
        except ValueError:
            named = [
                template for template in self.catalog.all()
                if template.name.casefold() == world_item.name.casefold()
            ]
            return named[0] if len(named) == 1 else None

    def _validate_character_capacity(
        self, character_id: int, template: ItemTemplate, quantity: int
    ) -> None:
        inventory = self.database.get_character_inventory(character_id)
        if inventory.current_storage(self.catalog) + template.weight * quantity > inventory.total_storage:
            raise InvalidTransferError("There is not enough regular inventory space.")

    def _resolve_character_item(
        self, inventory: InventoryState, query: str
    ) -> ItemInstance:
        exact = [item for item in inventory.items if item.instance_id == query]
        matches = exact or [
            item for item in inventory.items
            if item.template_id == query
            or self.catalog.get(item.template_id).name.casefold() == query.casefold()
        ]
        if not matches:
            raise InvalidTransferError(f"There is no inventory item named '{query}'.")
        if len(matches) > 1 and not exact:
            raise InvalidTransferError("That name is ambiguous; use the item instance ID.")
        return matches[0]
