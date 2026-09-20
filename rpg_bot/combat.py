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
    initiative_roll: int = 0
    initiative_score: int = 0
    acted_this_round: bool = False

    @property
    def initiative_key(self) -> tuple[int, int, str, str, str]:
        return (
            -self.initiative_score,
            -self.initiative_roll,
            self.kind.value,
            self.name.casefold(),
            self.source_id,
        )


@dataclass(frozen=True, slots=True)
class CombatLogEntry:
    id: int
    round_number: int
    event_type: str
    message: str
    created_at: str
    actor_kind: CombatantKind | None = None
    actor_source_id: str | None = None
    actor_name: str | None = None


@dataclass(frozen=True, slots=True)
class CombatScene:
    id: int
    guild_id: int
    room_id: str
    status: CombatStatus
    landmarks: tuple[CombatLandmark, ...] = ()
    routes: tuple[CombatRoute, ...] = ()
    combatants: tuple[CombatantState, ...] = ()
    round_number: int = 1
    current_turn_kind: CombatantKind | None = None
    current_turn_source_id: str | None = None
    log_entries: tuple[CombatLogEntry, ...] = ()

    def landmark(self, landmark_id: str) -> CombatLandmark | None:
        return next(
            (landmark for landmark in self.landmarks if landmark.id == landmark_id),
            None,
        )

    def initiative_order(self) -> tuple[CombatantState, ...]:
        return tuple(
            sorted(
                self.combatants,
                key=lambda combatant: combatant.initiative_key,
            )
        )

    def current_combatant(self) -> CombatantState | None:
        if self.current_turn_kind is None or self.current_turn_source_id is None:
            return None
        return next(
            (
                combatant
                for combatant in self.combatants
                if combatant.kind is self.current_turn_kind
                and combatant.source_id == self.current_turn_source_id
            ),
            None,
        )
