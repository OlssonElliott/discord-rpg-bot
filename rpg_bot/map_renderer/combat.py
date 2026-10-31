"""Player-facing, location-based combat map rendered from shared scene state.

This is a view of the existing graph, NOT a separate movement or combat model.
Only the DM dashboard and CombatService determine positions and valid routes.
"""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from typing import Mapping
from math import ceil, isfinite

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
ARRIVE = "#6bd2ac"
PARTIAL = "#e0a35a"


# The dashboard saves each node's *top-left* at x*1000, y*700.
# These values are deliberately not limited to 0..1: the editor permits
# extending the graph outside the original room box.
DASHBOARD_LAYOUT_WIDTH = 1000
DASHBOARD_LAYOUT_HEIGHT = 700
FALLBACK_POSITIONS = (
    (0.12, 0.18), (0.80, 0.18), (0.12, 0.82), (0.80, 0.82),
    (0.12, 0.34), (0.80, 0.34), (0.12, 0.66), (0.80, 0.66),
    (0.32, 0.34), (0.60, 0.34), (0.32, 0.66), (0.60, 0.66),
)
MAP_SIDE_MARGIN = 110
MAP_CONTENT_TOP = 160
MAP_CONTENT_BOTTOM = 125
MAX_MAP_HEIGHT = 1600


def location_layout(
    scene: CombatScene,
) -> tuple[dict[str, tuple[int, int]], int]:
    """Project the DM's saved, free-form graph without changing node order.

    Dashboard x/y are persisted in a 1000x700 logical coordinate space
    (including negative values). A single, uniform scale and translation
    fits the whole graph into the Discord image. No snapping or grid cells:
    relative distances, directions and edge crossings remain the same.
    """
    landmarks = scene.landmarks
    if not landmarks:
        return {}, MIN_MAP_HEIGHT

    # Match the dashboard's fallback coordinates for unsaved landmarks.
    # The Room Center is the special first node in the editor.
    original: dict[str, tuple[float, float]] = {}
    for index, landmark in enumerate(landmarks):
        fallback = (0.5, 0.5) if index == 0 else FALLBACK_POSITIONS[
            (index - 1) % len(FALLBACK_POSITIONS)
        ]
        x = landmark.x if landmark.x is not None and isfinite(landmark.x) else fallback[0]
        y = landmark.y if landmark.y is not None and isfinite(landmark.y) else fallback[1]
        original[landmark.id] = (
            x * DASHBOARD_LAYOUT_WIDTH,
            y * DASHBOARD_LAYOUT_HEIGHT,
        )

    xs = [point[0] for point in original.values()]
    ys = [point[1] for point in original.values()]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)

    # Keep node cards readable while allowing tall/narrow room layouts.
    # The original dashboard nodes are approximately 178x76 logical px.
    available_x = MAP_WIDTH - 2 * MAP_SIDE_MARGIN - NODE_WIDTH
    available_y = (
        MAX_MAP_HEIGHT - MAP_CONTENT_TOP - MAP_CONTENT_BOTTOM - NODE_HEIGHT
    )
    scale = min(
        1.0,
        available_x / span_x if span_x > 0 else 1.0,
        available_y / span_y if span_y > 0 else 1.0,
    )
    height = max(
        MIN_MAP_HEIGHT,
        ceil(MAP_CONTENT_TOP + NODE_HEIGHT + span_y * scale + MAP_CONTENT_BOTTOM),
    )

    mid_x = (min(xs) + max(xs)) / 2
    left_y = min(ys)
    # Center the graph within the available vertical area if it is short.
    used_height = span_y * scale + NODE_HEIGHT
    content_height = height - MAP_CONTENT_TOP - MAP_CONTENT_BOTTOM
    graph_top = MAP_CONTENT_TOP + (content_height - used_height) / 2
    positions = {
        name: (
            round(MAP_WIDTH / 2 + (x - mid_x) * scale),
            round(graph_top + NODE_HEIGHT / 2 + (y - left_y) * scale),
        )
        for name, (x, y) in original.items()
    }
    return positions, height


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


def render_combat_map(
    scene: CombatScene,
    room_name: str,
    *,
    move_costs: Mapping[str, int] | None = None,
    movement_remaining: int | None = None,
) -> BytesIO:
    """Return the shared combat map, optionally highlighting one player's moves.

    move_costs is a projection of CombatService movement paths. It only changes
    the image; it never grants movement, changes a route, or edits combat state.
    None means the normal public map, whereas {} means an empty move preview.
    """
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
    draw.text(
        (54, 34),
        "CHOOSE A LOCATION" if move_costs is not None else "COMBAT LOCATIONS",
        font=headline,
        fill=GOLD,
    )
    draw.text(
        (56, 79),
        _fit_text(draw, room_name, meta_font, MAP_WIDTH - 115),
        font=meta_font,
        fill=MUTED,
    )
    draw.line((54, 115, MAP_WIDTH - 54, 115), fill="#544933", width=2)
    if move_costs is not None:
        # Keep the movement budget in the header, above the map's node area.
        # The topmost landmark and its cost badge can begin around y=140.
        budget_text = (
            f"Movement remaining: "
            f"{movement_remaining if movement_remaining is not None else '?'}"
        )
        budget_width = draw.textlength(budget_text, font=meta_font)
        draw.text(
            (MAP_WIDTH - 55 - budget_width, 79),
            budget_text,
            font=meta_font,
            fill=PLAYER,
        )

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
        move_cost = move_costs.get(landmark.id) if move_costs is not None else None
        can_arrive = (
            move_cost is not None
            and movement_remaining is not None
            and move_cost <= movement_remaining
        )
        move_colour = ARRIVE if can_arrive else PARTIAL
        node_colour = (
            move_colour if move_cost is not None
            else GOLD if active_here else PANEL_EDGE
        )
        draw.rounded_rectangle(
            (x1, y1, x2, y2), radius=12,
            fill=PANEL, outline=node_colour,
            width=4 if move_cost is not None or active_here else 2,
        )
        if move_cost is not None:
            # Keep the movement label *outside* the location card, so a
            # combatant's name or cover annotation never gets overwritten.
            badge_label = f"{move_cost} MP" + ("" if can_arrive else " · PARTIAL")
            badge_width = round(draw.textlength(badge_label, font=label_font)) + 22
            badge_top = max(141, y1 - 29)
            draw.rounded_rectangle(
                (x1 + 2, badge_top, x1 + badge_width, badge_top + 24),
                radius=6,
                fill="#17352f" if can_arrive else "#45301c",
                outline=move_colour,
                width=1,
            )
            draw.text(
                (x1 + 12, badge_top + 3), badge_label,
                font=label_font, fill=move_colour,
            )
        # Use a smaller heading for long names instead of truncating them
        # into ambiguous labels such as "Northeast ...".
        node_title_font = title_font
        for size in (21, 19, 17, 15):
            if draw.textlength(landmark.name, font=node_title_font) <= NODE_WIDTH - 26:
                break
            node_title_font = _font(size, heading=True)
        draw.text(
            (x1 + 13, y1 + 8),
            _fit_text(draw, landmark.name, node_title_font, NODE_WIDTH - 26),
            font=node_title_font, fill=TEXT,
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
    if move_costs is not None:
        draw.text((56, footer_y), "Green: arrive", font=meta_font, fill=ARRIVE)
        draw.text((280, footer_y), "Amber: move partway", font=meta_font, fill=PARTIAL)
        draw.text((590, footer_y), "Select a destination below the map", font=meta_font, fill=MUTED)
    else:
        draw.text((56, footer_y), "P  Player", font=meta_font, fill=PLAYER)
        draw.text((210, footer_y), "E  Enemy", font=meta_font, fill=ENEMY)
        draw.text((365, footer_y), "Dashed route = blocked", font=meta_font, fill=MUTED)
    draw.text((MAP_WIDTH - 240, footer_y), f"Round {scene.round_number}", font=meta_font, fill=GOLD)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    image.close()
    output.seek(0)
    return output
