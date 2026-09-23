"""Item catalog, world inventory, and character transfer operations."""

from __future__ import annotations

from ...inventory import InventoryState, ItemInstance, ItemTemplate
from ..models import (
    InvalidTransferError,
    InventoryHolder,
    Item,
    ItemStack,
)


def create_item(
    service,
    item_id: str,
    name: str,
    description: str | None = None,
    *,
    stackable: bool = True,
) -> Item:
    return service.database.create_item(
        item_id, name, description, stackable=stackable
    )


def list_item_templates(service) -> tuple[ItemTemplate, ...]:
    return service.catalog.all()


def create_item_template(service, record: dict[str, object]) -> ItemTemplate:
    template = service.catalog.create(record)
    service._sync_catalog_item(template)
    service.migrate_legacy_character_items()
    return template


def update_item_template(
    service, template_id: str, record: dict[str, object]
) -> ItemTemplate:
    template = service.catalog.update(template_id, record)
    service._sync_catalog_item(template)
    return template


def place_catalog_item(
    service, holder: InventoryHolder, template_id: str, quantity: int = 1
) -> ItemStack:
    template = service.catalog.get(template_id)
    service._sync_catalog_item(template)
    return service.database.add_item(holder, template.template_id, quantity)


def set_item_quantity(
    service,
    holder: InventoryHolder,
    item_id: str,
    quantity: int,
) -> ItemStack:
    return service.database.set_world_item_quantity(holder, item_id, quantity)


def migrate_legacy_character_items(service) -> int:
    """Move recognizable old world stacks into the interactive inventory."""
    migrated = 0
    for character in service.list_characters():
        if character.character_id is None:
            continue
        holder = InventoryHolder.character(character.character_id)
        for stack in service.database.get_inventory(holder):
            template = service._template_for_world_item(stack.item)
            if template is None:
                continue
            service.database.take_world_item_into_character_inventory(
                holder,
                character.character_id,
                stack.item.id,
                template.template_id,
                quantity=stack.quantity,
                durability=template.durability,
                stackable=template.stackable,
            )
            migrated += stack.quantity
    return migrated


def place_item(
    service, holder: InventoryHolder, item_id: str, quantity: int = 1
) -> ItemStack:
    return service.database.add_item(holder, item_id, quantity)


def remove_item(service, holder: InventoryHolder, item_id: str) -> None:
    service.database.remove_item(holder, item_id)


def inventory(service, holder: InventoryHolder) -> tuple[ItemStack, ...]:
    stacks = service.database.get_inventory(holder)
    displayed: list[ItemStack] = []
    for stack in stacks:
        template = service._template_for_world_item(stack.item)
        stackable = (
            template.stackable
            if template is not None
            else stack.item.stackable
        )
        if stackable:
            displayed.append(stack)
        else:
            displayed.extend(
                ItemStack(stack.item, 1)
                for _ in range(stack.quantity)
            )
    return tuple(displayed)


def transfer_item(
    service,
    source: InventoryHolder,
    destination: InventoryHolder,
    item: str,
    quantity: int = 1,
) -> ItemStack:
    """Atomically resolve and transfer an item ID or unambiguous name."""
    return service.database.transfer_item(source, destination, item, quantity)


def take_loose_item(
    service, character_id: int, item: str, quantity: int = 1
) -> ItemStack:
    room = service.database.get_character_room(character_id)
    if room is None:
        raise InvalidTransferError("The character is not currently in a room.")
    source = InventoryHolder.room(room.id)
    template = service._catalog_template(source, item)
    if template is None:
        raise InvalidTransferError(
            "That item is not registered in the shared item library. "
            "Ask the DM to create it in the dashboard first."
        )
    service._validate_character_capacity(character_id, template, quantity)
    return service.database.take_world_item_into_character_inventory(
        source,
        character_id,
        item,
        template.template_id,
        quantity=quantity,
        durability=template.durability,
        stackable=template.stackable,
    )


def drop_item(
    service, character_id: int, item: str, quantity: int = 1
) -> ItemStack:
    if quantity < 1:
        raise InvalidTransferError("Quantity must be at least 1.")
    room = service.database.get_character_room(character_id)
    if room is None:
        raise InvalidTransferError("The character is not currently in a room.")
    inventory = service.database.get_character_inventory(character_id)
    matching_items = [
        inventory_item
        for inventory_item in inventory.items
        if inventory_item.template_id == item
    ]
    if matching_items:
        template = service.catalog.get(item)
        if not template.stackable and quantity > 1:
            if len(matching_items) < quantity:
                raise InvalidTransferError(
                    f"Only {len(matching_items)} × {template.name} is available."
                )
            moved = None
            for inventory_item in matching_items[:quantity]:
                moved = service.drop_item(
                    character_id, inventory_item.instance_id, 1
                )
            assert moved is not None
            return ItemStack(moved.item, quantity)
    try:
        selected = service._resolve_character_item(inventory, item)
    except InvalidTransferError:
        return service.transfer_item(
            InventoryHolder.character(character_id),
            InventoryHolder.room(room.id),
            item,
            quantity,
        )
    template = service.catalog.get(selected.template_id)
    world_item = Item(
        template.template_id
        if template.stackable
        else f"{template.template_id}__{selected.instance_id}",
        template.name,
        template.description,
        template.stackable,
    )
    return service.database.drop_character_inventory_item(
        character_id,
        selected.instance_id,
        InventoryHolder.room(room.id),
        world_item,
        quantity=quantity,
    )


def take_from_container(
    service,
    character_id: int,
    container: str,
    item: str,
    quantity: int = 1,
) -> ItemStack:
    room = service.database.get_character_room(character_id)
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
    container_state = service.database.get_container_instance(selected.id)
    if container_state is not None:
        if (
            container_state.hidden
            and not service.database.character_knows_container(
                character_id, selected.id
            )
        ):
            raise InvalidTransferError(
                f"There is no container named '{container}' here."
            )
        if container_state.is_locked:
            raise InvalidTransferError("That container is locked.")
    source = InventoryHolder.entity(selected.id)
    template = service._catalog_template(source, item)
    if template is None:
        raise InvalidTransferError(
            "That item is not registered in the shared item library. "
            "Ask the DM to create it in the dashboard first."
        )
    service._validate_character_capacity(character_id, template, quantity)
    return service.database.take_world_item_into_character_inventory(
        source,
        character_id,
        item,
        template.template_id,
        quantity=quantity,
        durability=template.durability,
        stackable=template.stackable,
    )


def catalog_template(
    service, holder: InventoryHolder, item_query: str
) -> ItemTemplate | None:
    stacks = service.database.get_inventory(holder)
    exact = [stack for stack in stacks if stack.item.id == item_query]
    matches = exact or [
        stack for stack in stacks
        if stack.item.name.casefold() == item_query.casefold()
    ]
    if len(matches) != 1:
        return None
    return service._template_for_world_item(matches[0].item)


def template_for_world_item(service, world_item: Item) -> ItemTemplate | None:
    try:
        return service.catalog.get(world_item.id)
    except ValueError:
        named = [
            template for template in service.catalog.all()
            if template.name.casefold() == world_item.name.casefold()
        ]
        return named[0] if len(named) == 1 else None


def sync_catalog_item(service, template: ItemTemplate) -> Item:
    return service.database.upsert_item(
        template.template_id,
        template.name,
        template.description,
        stackable=template.stackable,
    )


def validate_character_capacity(
    service, character_id: int, template: ItemTemplate, quantity: int
) -> None:
    inventory = service.database.get_character_inventory(character_id)
    added_slots = inventory.additional_slots(service.catalog, template)
    if (
        inventory.current_storage(service.catalog) + added_slots
        > inventory.storage_capacity(service.catalog)
    ):
        raise InvalidTransferError("There are not enough storage slots.")
    if (
        inventory.current_weight(service.catalog) + template.weight * quantity
        > inventory.carry_capacity()
    ):
        raise InvalidTransferError(
            "That would exceed the character's carry capacity."
        )


def resolve_character_item(
    service, inventory: InventoryState, query: str
) -> ItemInstance:
    exact = [item for item in inventory.items if item.instance_id == query]
    matches = exact or [
        item for item in inventory.items
        if item.template_id == query
        or service.catalog.get(item.template_id).name.casefold() == query.casefold()
    ]
    if not matches:
        raise InvalidTransferError(f"There is no inventory item named '{query}'.")
    if len(matches) > 1 and not exact:
        raise InvalidTransferError(
            "That name is ambiguous; use the item instance ID."
        )
    return matches[0]


class WorldItemMixin:
    create_item = create_item
    list_item_templates = list_item_templates
    create_item_template = create_item_template
    update_item_template = update_item_template
    place_catalog_item = place_catalog_item
    set_item_quantity = set_item_quantity
    migrate_legacy_character_items = migrate_legacy_character_items
    place_item = place_item
    remove_item = remove_item
    inventory = inventory
    transfer_item = transfer_item
    take_loose_item = take_loose_item
    drop_item = drop_item
    take_from_container = take_from_container
    _catalog_template = catalog_template
    _template_for_world_item = template_for_world_item
    _sync_catalog_item = sync_catalog_item
    _validate_character_capacity = validate_character_capacity
    _resolve_character_item = resolve_character_item
