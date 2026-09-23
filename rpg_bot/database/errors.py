"""Database-specific domain errors."""


class CharacterAlreadyExistsError(ValueError):
    """Raised when attempting to create a duplicate character."""


class CharacterNotFoundError(ValueError):
    """Raised when a requested character does not exist."""


class InvalidHitPointsError(ValueError):
    """Raised when a hit-point operation is invalid."""
