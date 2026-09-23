"""Deterministic landmark placement helpers for combat scenes."""

from __future__ import annotations

import re

from .models import CombatLandmark


LANDMARK_LAYOUT_SLOTS = (
    (0.12, 0.18),
    (0.80, 0.18),
    (0.12, 0.82),
    (0.80, 0.82),
    (0.12, 0.34),
    (0.32, 0.18),
    (0.60, 0.18),
    (0.80, 0.34),
    (0.12, 0.66),
    (0.32, 0.82),
    (0.60, 0.82),
    (0.80, 0.66),
    (0.32, 0.34),
    (0.60, 0.34),
    (0.32, 0.66),
    (0.60, 0.66),
)


def cardinal_direction(exit_name: str) -> str | None:
    aliases = {
        "n": "north",
        "north": "north",
        "e": "east",
        "east": "east",
        "s": "south",
        "south": "south",
        "w": "west",
        "west": "west",
    }
    directions = {
        aliases[token]
        for token in re.findall(r"[a-z]+", exit_name.casefold())
        if token in aliases
    }
    return next(iter(directions)) if len(directions) == 1 else None


def door_position(
    direction: str,
    index: int,
    count: int,
) -> tuple[float, float]:
    if count <= 1:
        offset = 0.0
    else:
        step = min(0.12, 0.48 / (count - 1))
        offset = (index - (count - 1) / 2) * step

    if direction == "north":
        return 0.5 + offset, 0.08
    if direction == "east":
        return 0.82, 0.5 + offset
    if direction == "south":
        return 0.5 + offset, 0.82
    return 0.08, 0.5 + offset


def next_open_position(
    landmarks: list[CombatLandmark] | tuple[CombatLandmark, ...],
) -> tuple[float, float]:
    occupied = [
        (landmark.x, landmark.y)
        for landmark in landmarks
        if landmark.x is not None and landmark.y is not None
    ]

    def is_free(candidate: tuple[float, float]) -> bool:
        x, y = candidate
        return all(
            abs(x - occupied_x) >= 0.20 or abs(y - occupied_y) >= 0.14
            for occupied_x, occupied_y in occupied
        )

    for candidate in LANDMARK_LAYOUT_SLOTS:
        if is_free(candidate):
            return candidate

    # Very crowded scenes still get a deterministic position instead of
    # failing to start. The normal slots above cover ordinary room layouts.
    return max(
        LANDMARK_LAYOUT_SLOTS,
        key=lambda candidate: min(
            (
                abs(candidate[0] - occupied_x) / 0.20
                + abs(candidate[1] - occupied_y) / 0.14
                for occupied_x, occupied_y in occupied
            ),
            default=float("inf"),
        ),
    )
