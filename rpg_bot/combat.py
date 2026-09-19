"""Pure domain models for landmark-based combat scenes."""

from dataclasses import dataclass
from enum import Enum


class CombatStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"


class LandmarkDistance(str, Enum):
    CLOSE = "close"
    FAR = "far"
    DISTANT = "distant"


class CombatantKind(str, Enum):
    CHARACTER = "character"
    ENEMY = "enemy"


class LandmarkRelation(str, Enum):
    AT = "at"
    BESIDE = "beside"
    BEHIND = "behind"
    ON = "on"
    INSIDE = "inside"


@dataclass(frozen=True, slots=True)
class CombatLandmark:
    id: str
    name: str
    description: str | None = None
    source_feature_id: str | None = None
    source_connection_id: str | None = None
    feature_type: str | None = None
    synthetic: bool = False
    x: float | None = None
    y: float | None = None


@dataclass(frozen=True, slots=True)
class CombatRoute:
    source_landmark_id: str
    destination_landmark_id: str
    distance: LandmarkDistance
    obstacle: str | None = None
    blocked: bool = False


@dataclass(frozen=True, slots=True)
class CombatantState:
    kind: CombatantKind
    source_id: str
    name: str
    landmark_id: str
    relation: LandmarkRelation = LandmarkRelation.AT


@dataclass(frozen=True, slots=True)
class CombatScene:
    id: int
    guild_id: int
    room_id: str
    status: CombatStatus
    landmarks: tuple[CombatLandmark, ...] = ()
    routes: tuple[CombatRoute, ...] = ()
    combatants: tuple[CombatantState, ...] = ()

    def landmark(self, landmark_id: str) -> CombatLandmark | None:
        return next(
            (landmark for landmark in self.landmarks if landmark.id == landmark_id),
            None,
        )
