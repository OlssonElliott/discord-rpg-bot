"""Transfers between world inventory stacks and character inventory."""

from __future__ import annotations

from uuid import uuid4

from ...world import (
    HolderKind,
    InvalidTransferError,
    InventoryHolder,
    Item,
    ItemStack,
)


class DatabaseWorldCharacterInventoryMixin:
    """Bridge shared world stacks and rich character inventory records."""

    def take_world_item_into_character_inventory(
        self,
        source: InventoryHolder,
        character_id: int,
        item_query: str,
        template_id: str,
        *,
        quantity: int,
        durability: int | None,
        stackable: bool,
    ) -> ItemStack:
        """Atomically move a room/entity stack into the rich character inventory."""
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, source)
            self._validate_holder(connection, InventoryHolder.character(character_id))
            item = self._resolve_held_item(connection, source, item_query)
            source_quantity = self._stack_quantity(connection, source, item.id)
            if source_quantity < quantity:
                raise InvalidTransferError(
                    f"Only {source_quantity} × {item.name} is available."
                )
            if not stackable and quantity != 1:
                raise InvalidTransferError(f"{item.name} is not stackable.")

            existing_rows = []
            if stackable:
                existing_rows = connection.execute(
                    """
                    SELECT instance_id, quantity FROM character_items
                    WHERE character_id = ? AND template_id = ?
                      AND parent_container_id IS NULL
                    ORDER BY rowid
                    """,
                    (character_id, template_id),
                ).fetchall()

            remaining = source_quantity - quantity
            if remaining:
                connection.execute(
                    """
                    UPDATE inventory_stacks SET quantity = ?
                    WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                    """,
                    (remaining, source.kind.value, source.id, item.id),
                )
            else:
                connection.execute(
                    """
                    DELETE FROM inventory_stacks
                    WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                    """,
                    (source.kind.value, source.id, item.id),
                )

            if existing_rows:
                primary = existing_rows[0]
                combined_quantity = quantity + sum(
                    row["quantity"] for row in existing_rows
                )
                connection.execute(
                    """
                    UPDATE character_items SET quantity = ?
                    WHERE instance_id = ?
                    """,
                    (combined_quantity, primary["instance_id"]),
                )
                duplicate_ids = [
                    row["instance_id"] for row in existing_rows[1:]
                ]
                if duplicate_ids:
                    placeholders = ", ".join("?" for _ in duplicate_ids)
                    connection.execute(
                        f"""
                        DELETE FROM character_items
                        WHERE instance_id IN ({placeholders})
                        """,
                        duplicate_ids,
                    )
            else:
                connection.execute(
                    """
                    INSERT INTO character_items (
                        instance_id, character_id, template_id, quantity, durability
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (uuid4().hex, character_id, template_id, quantity, durability),
                )
            if source.kind is HolderKind.ROOM:
                self._queue_map_refresh_for_room(connection, source.id)
        return ItemStack(item, quantity)

    def drop_character_inventory_item(
        self,
        character_id: int,
        instance_id: str,
        destination: InventoryHolder,
        item: Item,
        *,
        quantity: int,
    ) -> ItemStack:
        """Atomically move a rich inventory item into a room/entity stack."""
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, destination)
            row = connection.execute(
                """
                SELECT template_id, quantity, parent_container_id
                FROM character_items
                WHERE character_id = ? AND instance_id = ?
                """,
                (character_id, instance_id),
            ).fetchone()
            if row is None:
                raise InvalidTransferError("That item is not in this inventory.")
            if row["parent_container_id"] is not None:
                raise InvalidTransferError("Move the item out of its container first.")
            if connection.execute(
                "SELECT 1 FROM character_equipment WHERE character_id = ? AND item_instance_id = ?",
                (character_id, instance_id),
            ).fetchone():
                raise InvalidTransferError("Unequip that item before dropping it.")
            if connection.execute(
                "SELECT 1 FROM character_items WHERE parent_container_id = ? LIMIT 1",
                (instance_id,),
            ).fetchone():
                raise InvalidTransferError("Empty that container before dropping it.")
            if row["quantity"] < quantity:
                raise InvalidTransferError(
                    f"Only {row['quantity']} × {item.name} is available."
                )
            if not item.stackable and quantity != 1:
                raise InvalidTransferError(f"{item.name} is not stackable.")

            connection.execute(
                """
                INSERT INTO items (id, name, description, stackable)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    stackable = excluded.stackable
                """,
                (item.id, item.name, item.description, int(item.stackable)),
            )
            destination_quantity = self._stack_quantity(connection, destination, item.id)
            if not item.stackable and destination_quantity:
                raise InvalidTransferError(f"{item.name} is not stackable.")

            remaining = row["quantity"] - quantity
            if remaining:
                connection.execute(
                    "UPDATE character_items SET quantity = ? WHERE instance_id = ?",
                    (remaining, instance_id),
                )
            else:
                connection.execute(
                    "DELETE FROM character_items WHERE instance_id = ?",
                    (instance_id,),
                )
            connection.execute(
                """
                INSERT INTO inventory_stacks (holder_kind, holder_id, item_id, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(holder_kind, holder_id, item_id) DO UPDATE
                SET quantity = quantity + excluded.quantity
                """,
                (destination.kind.value, destination.id, item.id, quantity),
            )
            if destination.kind is HolderKind.ROOM:
                self._queue_map_refresh_for_room(connection, destination.id)
        return ItemStack(item, quantity)
