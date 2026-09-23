"""Data models for player-to-player transfers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GiveOffer:
    sender_user_id: int
    recipient_user_id: int
    sender_character_id: int | None = None
    recipient_character_id: int | None = None
    item_instance_id: str | None = None
    quantity: int = 0
    copper: int = 0
    silver: int = 0
    gold: int = 0

    @property
    def is_item(self) -> bool:
        return self.item_instance_id is not None


@dataclass(frozen=True)
class RoomRecipient:
    user_id: int
    character_id: int
    name: str
