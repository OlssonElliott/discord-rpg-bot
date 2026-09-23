"""SQLite persistence for RPG characters."""

from pathlib import Path

from .errors import (
    CharacterAlreadyExistsError,
    CharacterNotFoundError,
    InvalidHitPointsError,
)
from .characters.combat import DatabaseCharacterCombatMixin
from .core import DatabaseCoreMixin
from .characters.sheet import DatabaseCharacterSheetMixin
from .characters.inventory import DatabaseCharacterInventoryMixin
from .characters.queries import DatabaseCharacterQueriesMixin
from .characters.knowledge import DatabaseCharacterKnowledgeMixin
from .characters.schema import DatabaseCharacterSchemaMixin
from .characters.world import DatabaseCharacterWorldMixin
from .characters.lifecycle import DatabaseCharactersMixin
from .characters.admin import DatabaseCharacterAdminMixin
from .containers.templates import DatabaseContainerTemplatesMixin
from .containers.repository import DatabaseContainersMixin
from .connections.state import DatabaseConnectionStateMixin
from .connections.repository import DatabaseConnectionsMixin
from .connections.traps import DatabaseConnectionTrapsMixin
from .dungeons import DatabaseDungeonsMixin
from .enemies.templates import DatabaseEnemyTemplatesMixin
from .enemies.repository import DatabaseEnemiesMixin
from .initialization import DatabaseInitializationMixin
from .player_view import DatabasePlayerViewMixin
from .private_views import DatabasePrivateViewsMixin
from .preferences import DatabasePreferencesMixin
from .rooms.features import DatabaseRoomFeaturesMixin
from .rooms.repository import DatabaseRoomsMixin
from .world.entities import DatabaseWorldEntitiesMixin
from .world.character_inventory import DatabaseWorldCharacterInventoryMixin
from .world.inventory import DatabaseWorldInventoryMixin
from .world.items import DatabaseWorldItemsMixin
from .world.schema import DatabaseWorldSchemaMixin


class Database(
    DatabasePreferencesMixin,
    DatabaseEnemyTemplatesMixin,
    DatabaseEnemiesMixin,
    DatabasePrivateViewsMixin,
    DatabasePlayerViewMixin,
    DatabaseCharacterCombatMixin,
    DatabaseWorldEntitiesMixin,
    DatabaseWorldCharacterInventoryMixin,
    DatabaseWorldItemsMixin,
    DatabaseWorldInventoryMixin,
    DatabaseRoomFeaturesMixin,
    DatabaseContainerTemplatesMixin,
    DatabaseContainersMixin,
    DatabaseCharacterSheetMixin,
    DatabaseCharacterInventoryMixin,
    DatabaseCharacterAdminMixin,
    DatabaseCharacterQueriesMixin,
    DatabaseCharactersMixin,
    DatabaseDungeonsMixin,
    DatabaseRoomsMixin,
    DatabaseConnectionTrapsMixin,
    DatabaseConnectionStateMixin,
    DatabaseConnectionsMixin,
    DatabaseCharacterKnowledgeMixin,
    DatabaseCharacterWorldMixin,
    DatabaseInitializationMixin,
    DatabaseCharacterSchemaMixin,
    DatabaseWorldSchemaMixin,
    DatabaseCoreMixin,
):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
