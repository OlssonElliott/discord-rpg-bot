"""Dice rolling domain package."""

from .roller import *  # noqa: F401,F403

# Kept available for compatibility with existing test patch targets.
from .roller import secrets as secrets  # noqa: F401
