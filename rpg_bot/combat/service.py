"""Application service for landmark-based combat scene state."""

import random
import re

from .models import CombatScene
from .attacks import CombatAttackMixin
from .auto_connect import CombatAutoConnectMixin
from .death_saves import CombatDeathSaveMixin
from .enemy_management import CombatEnemyManagementMixin
from .errors import CombatError
from .landmarks import CombatLandmarkMixin
from .lifecycle import CombatLifecycleMixin
from .movement import CombatMovementMixin
from .repository import CombatRepository
from .rules import CombatRulesMixin
from .turns import CombatTurnMixin
from ..database import Database
from ..world.service import WorldService


class CombatService(
    CombatRulesMixin,
    CombatLifecycleMixin,
    CombatDeathSaveMixin,
    CombatAttackMixin,
    CombatEnemyManagementMixin,
    CombatTurnMixin,
    CombatAutoConnectMixin,
    CombatLandmarkMixin,
    CombatMovementMixin,
):
    """UI-independent combat scene orchestration."""

    CENTER_LANDMARK_ID = "room:center"
    def __init__(self, database: Database) -> None:
        self.database = database
        self.world = WorldService(database)
        self.repository = CombatRepository(database.path)
        self.repository.initialize()

    @staticmethod
    def _roll_initiative(insight_modifier: int) -> tuple[int, int]:
        roll = random.randint(1, 20)
        return roll, roll + insight_modifier

    @staticmethod
    def _roll_d20(
        *,
        disadvantage: bool = False,
    ) -> tuple[tuple[int, ...], int]:
        rolls = tuple(
            random.randint(1, 20)
            for _ in range(2 if disadvantage else 1)
        )
        return rolls, min(rolls) if disadvantage else rolls[0]

    @staticmethod
    def _roll_die(sides: int) -> int:
        return random.randint(1, sides)

    @staticmethod
    def _roll_damage_expression(
        expression: str,
    ) -> tuple[tuple[int, ...], int]:
        match = re.fullmatch(
            r"\s*(\d*)d(\d+)([+-]\d+)?\s*",
            expression.casefold(),
        )
        if match is None:
            raise CombatError(
                f"Unsupported enemy damage expression '{expression}'."
            )
        count = int(match.group(1) or "1")
        die = int(match.group(2))
        bonus = int(match.group(3) or "0")
        if count < 1 or die < 1:
            raise CombatError(
                f"Unsupported enemy damage expression '{expression}'."
            )
        rolls = tuple(random.randint(1, die) for _ in range(count))
        return rolls, max(0, sum(rolls) + bonus)

    def _require_current(self, guild_id: int) -> CombatScene:
        scene = self.current(guild_id)
        if scene is None:
            raise CombatError("There is no active combat scene.")
        return scene
