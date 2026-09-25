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


class RouteTerrain(str, Enum):
    NORMAL = "normal"
    DIFFICULT = "difficult"


class CombatantKind(str, Enum):
    CHARACTER = "character"
    ENEMY = "enemy"


class LandmarkRelation(str, Enum):
    AT = "at"
    BEHIND = "behind"


class CoverLevel(str, Enum):
    NONE = "none"
    HALF = "half"
    FULL = "full"


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
    cover: CoverLevel = CoverLevel.NONE


@dataclass(frozen=True, slots=True)
class CombatRouteEffect:
    id: str
    name: str
    effect_type: str
    blocks_movement: bool = False
    movement_cost_modifier: int = 0
    remaining_rounds: int | None = None


@dataclass(frozen=True, slots=True)
class CombatRoute:
    source_landmark_id: str
    destination_landmark_id: str
    distance: LandmarkDistance
    terrain: RouteTerrain = RouteTerrain.NORMAL
    base_blocked: bool = False
    automatic: bool = False
    effects: tuple[CombatRouteEffect, ...] = ()

    @property
    def base_movement_cost(self) -> int:
        return {
            LandmarkDistance.CLOSE: 1,
            LandmarkDistance.FAR: 3,
            LandmarkDistance.DISTANT: 5,
        }[self.distance]

    @property
    def movement_cost(self) -> int:
        cost = self.base_movement_cost
        if self.terrain is RouteTerrain.DIFFICULT:
            cost *= 2
        cost += sum(
            effect.movement_cost_modifier
            for effect in self.effects
        )
        return max(1, cost)

    @property
    def blocked(self) -> bool:
        return (
            self.base_blocked
            or any(effect.blocks_movement for effect in self.effects)
        )


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
    movement_budget: int = 3
    movement_remaining: int = 3
    route_source_landmark_id: str | None = None
    route_destination_landmark_id: str | None = None
    route_progress: int = 0
    route_cost: int = 0
    standard_action_spent: bool = False

    @property
    def is_between_landmarks(self) -> bool:
        return (
            self.route_source_landmark_id is not None
            and self.route_destination_landmark_id is not None
            and self.route_cost > 0
            and 0 < self.route_progress < self.route_cost
        )

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
class DamageRoll:
    die: int
    damage_type: str
    roll: int


@dataclass(frozen=True, slots=True)
class AttackResult:
    attacker_kind: CombatantKind
    attacker_source_id: str
    attacker_name: str
    target_kind: CombatantKind
    target_source_id: str
    target_name: str
    weapon_name: str
    attack_attribute: str
    attack_roll: int
    attack_modifier: int
    attack_total: int
    defense_dc: int
    hit: bool
    critical: bool
    damage_rolls: tuple[DamageRoll, ...] = ()
    raw_damage: int = 0
    reduction: int = 0
    reduction_type: str = "armor"
    final_damage: int = 0
    target_hp: int = 0
    target_max_hp: int = 0
    target_defeated: bool = False


@dataclass(frozen=True, slots=True)
class EnemyAttackResult:
    attacker_source_id: str
    attacker_name: str
    target_source_id: str
    target_name: str
    attack_profile: str
    attack_dc: int
    defense_method: str
    defense_attribute: str
    defense_roll: int
    defense_modifier: int
    defense_total: int
    defended: bool
    critical_defense: bool
    damage_expression: str
    damage_rolls: tuple[int, ...] = ()
    raw_damage: int = 0
    armor_reduction: int = 0
    final_damage: int = 0
    target_hp: int = 0
    target_max_hp: int = 0
    target_down: bool = False
    target_status: str = "active"
    target_dead: bool = False


@dataclass(frozen=True, slots=True)
class DeathSaveResult:
    character_source_id: str
    character_name: str
    hp: int
    dc: int
    roll: int
    modifier: int
    total: int
    success: bool
    failed_death_saves: int
    status: str


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
