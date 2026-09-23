"""Deterministic application service for world state and item transfers."""

from ...database import Database
from ...inventory import DEFAULT_ITEM_CATALOG_PATH, ItemCatalog
from .characters import WorldCharacterMixin
from .containers import WorldContainerMixin
from .enemies import WorldEnemyMixin
from .entities import WorldEntityMixin
from .items import WorldItemMixin
from .room_features import WorldRoomFeatureMixin
from .topology import WorldTopologyMixin


class WorldService(
    WorldCharacterMixin,
    WorldContainerMixin,
    WorldEnemyMixin,
    WorldEntityMixin,
    WorldItemMixin,
    WorldRoomFeatureMixin,
    WorldTopologyMixin,
):
    """UI-independent entry point for all world mutations."""

    def __init__(self, database: Database, catalog: ItemCatalog | None = None) -> None:
        self.database = database
        self.catalog = catalog or ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)
