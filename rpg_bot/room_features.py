"""Lightweight descriptive features attached to rooms."""

from dataclasses import dataclass
from enum import Enum


class RoomFeatureType(str, Enum):
    FURNITURE = "furniture"
    DECORATION = "decoration"
    STRUCTURE = "structure"
    ENVIRONMENTAL = "environmental"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class RoomFeatureTemplate:
    id: str
    name: str
    feature_type: RoomFeatureType
    description: str | None = None


@dataclass(frozen=True, slots=True)
class RoomFeature:
    id: str
    room_id: str
    name: str
    feature_type: RoomFeatureType
    description: str | None = None

    @property
    def look_text(self) -> str:
        """Return the descriptive text a future /look command can reuse."""
        return self.description or self.name
