"""Shared mechanical lock validation for doors and loot containers."""


def validate_lock(
    has_lock: bool,
    is_locked: bool,
    is_broken: bool,
    unlock_difficulty: int | None,
    *,
    subject: str,
) -> int | None:
    """Validate common lock state and normalize its active difficulty."""
    if not has_lock:
        if is_locked or is_broken:
            raise ValueError(
                f"A {subject} without a lock cannot be locked or broken."
            )
        return None
    if is_locked and is_broken:
        raise ValueError("A broken lock cannot also be locked.")
    if is_broken or not is_locked:
        return None
    if (
        isinstance(unlock_difficulty, bool)
        or not isinstance(unlock_difficulty, int)
        or not 1 <= unlock_difficulty <= 30
    ):
        raise ValueError("Unlock difficulty must be an integer from 1 to 30.")
    return unlock_difficulty
