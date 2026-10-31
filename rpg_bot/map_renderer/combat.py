"""Player-facing, location-based combat map rendered from shared scene state.

This is a view of the existing graph, NOT a separate movement or combat model.
Only the DM dashboard and CombatService determine positions and valid routes.
"""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from math import ceil, isfinite, sqrt

from PIL import Image, ImageDraw

from ..combat.models import CombatScene, CombatantKind, CombatantState
from .canvas import _font


MAP_WIDTH = 1280
MIN_MAP_HEIGHT = 820
NODE_WIDTH = 190
NODE_HEIGHT = 94

BG = "#101825"
PANEL = "#1b2a3c"
PANEL_EDGE = "#506179"
GOLD = "#d6a356"
TEXT = "#ede9de"
MUTED = "#a3b0c0"
PLAYER = "#69bfae"
ENEMY = "#e58f81"


def location_layout(
    scene: CombatScene,
) -> tuple[dict[str, tuple[int, int]], int]:
    """Fit saved dashboard positions into readable, nonoverlapping map cells.

    The grid is only a *drawing layout*. Combat movement continues to follow
    the true landmark/route graph, including intermediate route progress.
    """
    landmarks = scene.landmarks
    count = len(landmarks)
    if not count:
        return {}, MIN_MAP_HEIGHT

    columns = min(5, max(3, ceil(sqrt(count * 1.5))))
    rows = max(3, ceil(count / columns))
    height = max(MIN_MAP_HEIGHT, 240 + rows * 145)
    known_x = [
        landmark.x
        for landmark in landmarks
        if landmark.x is not None and isfinite(landmark.x)
    ]
    known_y = [
        landmark.y
        for landmark in landmarks
        if landmark.y is not None and isfinite(landmark.y)
    ]
    left, right = (min(known_x), max(known_x)) if known_x else (0.0, 1.0)
    top, bottom = (min(known_y), max(known_y)) if known_y else (0.0, 1.0)
    free = {(col, row) for col in range(columns) for row in range(rows)}
    locations = {}

    for index, landmark in enumerate(landmarks):
        x = landmark.x if landmark.x is not None and isfinite(landmark.x) else None
        y = landmark.y if landmark.y is not None and isfinite(landmark.y) else None
        target_col = (
            (x - left) / (right - left) * (columns - 1)
            if x is not None and right != left else index % columns
        )
        target_row = (
            (y - top) / (bottom - top) * (rows - 1)
            if y is not None and bottom != top else index // columns
        )
        col, row = min(
            free,
            key=lambda cell: (
                (cell[0] - target_col) ** 2 + (cell[1] - target_row) ** 2,
                cell[1],
                cell[0],
            ),
        )
        free.remove((col, row))
        px = round(142 + col * (MAP_WIDTH - 284) / max(1, columns - 1))
        py = round(190 + row * (height - 320) / max(1, rows - 1))
        locations[landmark.id] = (px, py)
    return locations, height


def _fit_text(draw, text: str, font, max_width: int) -> str:
    """Elide labels without ever letting text escape its node."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "...", font=font) > max_width:
        text = text[:-1]
    return text + "..." if text else "..."


def _token(draw, x: int, y: int, combatant: CombatantState, *, current: bool):
    colour = PLAYER if combatant.kind is CombatantKind.CHARACTER else ENEMY
    font = _font(15)
    name_font = _font(19)
    draw.rounded_rectangle(
        (x, y, x + 27, y + 27),
        radius=7,
        fill=colour,
        outline=GOLD if current else colour,
        width=2 if current else 1,
    )
    draw.text(
        (x + 8, y + 3),
        "P" if combatant.kind is CombatantKind.CHARACTER else "E",
        fill=BG,
        font=font,
    )
    draw.text(
        (x + 34, y + 2),
        _fit_text(draw, combatant.name, name_font, 105),
        fill=GOLD if current else TEXT,
        font=name_font,
    )


def _draw_route(draw, start: tuple[int, int], end: tuple[int, int], *, blocked: bool, difficult: bool):
    colour = "#b46262" if blocked else "#9c783f" if difficult else "#647790"
    if blocked:
        segments = 16
        for index in range(0, segments, 2):
            first = index / segments
            second = (index + 1) / segments
            draw.line(
                (
                    start[0] + (end[0] - start[0]) * first,
                    start[1] + (end[1] - start[1]) * first,
                    start[0] + (end[0] - start[0]) * second,
                    start[1] + (end[1] - start[1]) * second,
                ),
                fill=colour,
                width=4,
            )
    else:
        draw.line((*start, *end), fill=colour, width=4)


def render_combat_map(scene: CombatScene, room_name: str) -> BytesIO:
    """Return a Discord-ready PNG of locations, connections and combatants."""
    locations, height = location_layout(scene)
    image = Image.new("RGB", (MAP_WIDTH, height), BG)
    draw = ImageDraw.Draw(image)
    headline = _font(34, heading=True)
    title_font = _font(23, heading=True)
    label_font = _font(16)
    meta_font = _font(19)

    # Restrained cartographic background, independent of the editor theme.
    for x in range(28, MAP_WIDTH - 20, 30):
        for y in range(105, height - 70, 30):
            draw.point((x, y), fill="#233142")
    draw.rounded_rectangle(
        (22, 18, MAP_WIDTH - 22, height - 20),
        radius=18,
        outline="#75603e",
        width=3,
    )
    draw.text((54, 34), "COMBAT LOCATIONS", font=headline, fill=GOLD)
    draw.text(
        (56, 79),
        _fit_text(draw, room_name, meta_font, MAP_WIDTH - 115),
        font=meta_font,
        fill=MUTED,
    )
    draw.line((54, 115, MAP_WIDTH - 54, 115), fill="#544933", width=2)

    for route in scene.routes:
        start = locations.get(route.source_landmark_id)
        end = locations.get(route.destination_landmark_id)
        if start is None or end is None:
            continue
        _draw_route(
            draw, start, end,
            blocked=route.blocked,
            difficult=route.terrain.value == "difficult",
        )

    occupants: dict[str, list[CombatantState]] = defaultdict(list)
    travelling = []
    for combatant in scene.combatants:
        if combatant.is_between_landmarks:
            travelling.append(combatant)
        else:
            occupants[combatant.landmark_id].append(combatant)

    current = scene.current_combatant()
    for landmark in scene.landmarks:
        center = locations.get(landmark.id)
        if center is None:
            continue
        cx, cy = center
        x1 = cx - NODE_WIDTH // 2
        y1 = cy - NODE_HEIGHT // 2
        x2 = x1 + NODE_WIDTH
        y2 = y1 + NODE_HEIGHT
        at_location = occupants.get(landmark.id, [])
        active_here = current is not None and any(
            entry.kind is current.kind and entry.source_id == current.source_id
            for entry in at_location
        )
        draw.rounded_rectangle(
            (x1, y1, x2, y2), radius=12,
            fill=PANEL, outline=GOLD if active_here else PANEL_EDGE,
            width=4 if active_here else 2,
        )
        draw.text(
            (x1 + 13, y1 + 8),
            _fit_text(draw, landmark.name, title_font, NODE_WIDTH - 26),
            font=title_font, fill=TEXT,
        )
        if at_location:
            for index, combatant in enumerate(at_location[:2]):
                _token(
                    draw, x1 + 13, y1 + 37 + index * 26, combatant,
                    current=current is not None
                    and combatant.kind is current.kind
                    and combatant.source_id == current.source_id,
                )
            if len(at_location) > 2:
                draw.text(
                    (x2 - 64, y2 - 22),
                    f"+{len(at_location) - 2}",
                    font=label_font, fill=MUTED,
                )
        else:
            annotation = (
                f"{landmark.cover.value.upper()} COVER"
                if landmark.cover.value != "none"
                else "LOCATION"
            )
            draw.text(
                (x1 + 14, y2 - 27),
                annotation,
                font=label_font, fill=GOLD if landmark.cover.value != "none" else MUTED,
            )

    # Combatants in transit are rendered on the actual connecting route,
    # not incorrectly snapped to either location.
    for combatant in travelling:
        start = locations.get(combatant.route_source_landmark_id or "")
        end = locations.get(combatant.route_destination_landmark_id or "")
        if start is None or end is None or combatant.route_cost <= 0:
            continue
        fraction = min(1.0, max(0.0, combatant.route_progress / combatant.route_cost))
        x = round(start[0] + (end[0] - start[0]) * fraction)
        y = round(start[1] + (end[1] - start[1]) * fraction)
        x = max(10, min(MAP_WIDTH - 175, x))
        y = max(125, min(height - 125, y - 18))
        draw.rounded_rectangle(
            (x - 6, y - 6, x + 164, y + 38),
            radius=9, fill="#25384b", outline=GOLD,
            width=2,
        )
        _token(
            draw, x + 1, y + 2, combatant,
            current=current is not None
            and combatant.kind is current.kind
            and combatant.source_id == current.source_id,
        )

    footer_y = height - 62
    draw.line((54, footer_y - 13, MAP_WIDTH - 54, footer_y - 13), fill="#544933", width=2)
    draw.text((56, footer_y), "P  Player", font=meta_font, fill=PLAYER)
    draw.text((210, footer_y), "E  Enemy", font=meta_font, fill=ENEMY)
    draw.text((365, footer_y), "Dashed route = blocked", font=meta_font, fill=MUTED)
    draw.text((MAP_WIDTH - 240, footer_y), f"Round {scene.round_number}", font=meta_font, fill=GOLD)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    image.close()
    output.seek(0)
    return output
