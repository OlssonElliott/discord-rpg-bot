"""Shared world inventory persistence for the database facade."""

from __future__ import annotations

import sqlite3
from ...world import (
    HolderKind,
    InvalidTransferError,
    InventoryHolder,
    Item,
    ItemStack,
    NotFoundError,
)


class DatabaseWorldInventoryMixin:
    """Persist shared item stacks and transfers between world holders."""

    def add_item(
        self, holder: InventoryHolder, item_id: str, quantity: int = 1
    ) -> ItemStack:
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, holder)
            item = self._require_item(connection, item_id)
            existing = self._stack_quantity(connection, holder, item.id)
            if not item.stackable and (quantity != 1 or existing):
                raise InvalidTransferError(f"{item.name} is not stackable.")
            connection.execute(
                """
                INSERT INTO inventory_stacks (holder_kind, holder_id, item_id, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(holder_kind, holder_id, item_id) DO UPDATE
                SET quantity = quantity + excluded.quantity
                """,
                (holder.kind.value, holder.id, item.id, quantity),
            )
            if holder.kind is HolderKind.ROOM:
                self._queue_map_refresh_for_room(connection, holder.id)
        return ItemStack(item, existing + quantity)

    def remove_item(self, holder: InventoryHolder, item_id: str) -> None:
        """Remove an entire item stack from a world inventory."""
        with self._connect() as connection:
            self._validate_holder(connection, holder)
            cursor = connection.execute(
                """
                DELETE FROM inventory_stacks
                WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                """,
                (holder.kind.value, holder.id, item_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Item '{item_id}' does not exist in that inventory."
                )
            if holder.kind is HolderKind.ROOM:
                self._queue_map_refresh_for_room(connection, holder.id)

    def get_inventory(self, holder: InventoryHolder) -> tuple[ItemStack, ...]:
        with self._connect() as connection:
            self._validate_holder(connection, holder)
            rows = connection.execute(
                """
                SELECT i.id, i.name, i.description, i.stackable, s.quantity
                FROM inventory_stacks AS s JOIN items AS i ON i.id = s.item_id
                WHERE s.holder_kind = ? AND s.holder_id = ?
                ORDER BY i.name COLLATE NOCASE, i.id
                """,
                (holder.kind.value, holder.id),
            ).fetchall()
            return tuple(
                ItemStack(
                    Item(row["id"], row["name"], row["description"], bool(row["stackable"])),
                    row["quantity"],
                )
                for row in rows
            )

    def transfer_item(
        self,
        source: InventoryHolder,
        destination: InventoryHolder,
        item_query: str,
        quantity: int = 1,
    ) -> ItemStack:
        if source == destination:
            raise InvalidTransferError("Source and destination must be different.")
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, source)
            self._validate_holder(connection, destination)
            item = self._resolve_held_item(connection, source, item_query)
            source_quantity = self._stack_quantity(connection, source, item.id)
            if source_quantity < quantity:
                raise InvalidTransferError(
                    f"Only {source_quantity} × {item.name} is available."
                )
            destination_quantity = self._stack_quantity(connection, destination, item.id)
            if not item.stackable and (quantity != 1 or destination_quantity):
                raise InvalidTransferError(f"{item.name} is not stackable.")

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
            connection.execute(
                """
                INSERT INTO inventory_stacks (holder_kind, holder_id, item_id, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(holder_kind, holder_id, item_id) DO UPDATE
                SET quantity = quantity + excluded.quantity
                """,
                (destination.kind.value, destination.id, item.id, quantity),
            )
            for holder in (source, destination):
                if holder.kind is HolderKind.ROOM:
                    self._queue_map_refresh_for_room(connection, holder.id)
        return ItemStack(item, quantity)

    def set_world_item_quantity(
        self,
        holder: InventoryHolder,
        item_id: str,
        quantity: int,
    ) -> ItemStack:
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, holder)
            item = self._require_item(connection, item_id)
            if not item.stackable and quantity != 1:
                raise InvalidTransferError(f"{item.name} is not stackable.")
            cursor = connection.execute(
                """
                UPDATE inventory_stacks SET quantity = ?
                WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                """,
                (quantity, holder.kind.value, holder.id, item.id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Item '{item_id}' does not exist in that inventory."
                )
        return ItemStack(item, quantity)

    @staticmethod
    def _validate_holder(
        connection: sqlite3.Connection, holder: InventoryHolder
    ) -> None:
        if holder.kind.value == "character":
            try:
                character_id = int(holder.id)
            except ValueError as error:
                raise NotFoundError(f"Character '{holder.id}' does not exist.") from error
            exists = connection.execute(
                "SELECT 1 FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
        elif holder.kind.value == "room":
            exists = connection.execute(
                "SELECT 1 FROM rooms WHERE id = ?", (holder.id,)
            ).fetchone()
        else:
            exists = connection.execute(
                "SELECT 1 FROM world_entities WHERE id = ?", (holder.id,)
            ).fetchone()
        if exists is None:
            raise NotFoundError(
                f"{holder.kind.value.title()} holder '{holder.id}' does not exist."
            )

    @staticmethod
    def _stack_quantity(
        connection: sqlite3.Connection, holder: InventoryHolder, item_id: str
    ) -> int:
        row = connection.execute(
            """
            SELECT quantity FROM inventory_stacks
            WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
            """,
            (holder.kind.value, holder.id, item_id),
        ).fetchone()
        return row["quantity"] if row else 0

    @staticmethod
    def _resolve_held_item(
        connection: sqlite3.Connection,
        holder: InventoryHolder,
        item_query: str,
    ) -> Item:
        query = item_query.strip()
        rows = connection.execute(
            """
            SELECT i.id, i.name, i.description, i.stackable
            FROM inventory_stacks AS s JOIN items AS i ON i.id = s.item_id
            WHERE s.holder_kind = ? AND s.holder_id = ?
              AND (i.id = ? OR i.name = ? COLLATE NOCASE)
            ORDER BY CASE WHEN i.id = ? THEN 0 ELSE 1 END
            """,
            (holder.kind.value, holder.id, query, query, query),
        ).fetchall()
        if not rows:
            raise InvalidTransferError(f"The source does not contain '{item_query}'.")
        exact_ids = [row for row in rows if row["id"] == query]
        if not exact_ids and len(rows) > 1:
            raise InvalidTransferError(
                f"More than one item is named '{item_query}'; use an item ID."
            )
        row = exact_ids[0] if exact_ids else rows[0]
        return Item(row["id"], row["name"], row["description"], bool(row["stackable"]))

