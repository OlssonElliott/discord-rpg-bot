"""Pure combat positioning and pathfinding helpers."""

from __future__ import annotations

import heapq

from .models import CombatRoute, CombatScene, CombatantState


def same_combat_position(
    first: CombatantState,
    second: CombatantState,
) -> bool:
    if first.is_between_landmarks != second.is_between_landmarks:
        return False
    if not first.is_between_landmarks:
        return first.landmark_id == second.landmark_id

    first_ids = {
        first.route_source_landmark_id,
        first.route_destination_landmark_id,
    }
    second_ids = {
        second.route_source_landmark_id,
        second.route_destination_landmark_id,
    }
    if first_ids != second_ids or first.route_cost != second.route_cost:
        return False

    canonical_start = min(
        first.route_source_landmark_id or "",
        first.route_destination_landmark_id or "",
    )
    first_progress = (
        first.route_progress
        if first.route_source_landmark_id == canonical_start
        else first.route_cost - first.route_progress
    )
    second_progress = (
        second.route_progress
        if second.route_source_landmark_id == canonical_start
        else second.route_cost - second.route_progress
    )
    return first_progress == second_progress


def route_between(
    scene: CombatScene,
    first_landmark_id: str,
    second_landmark_id: str,
) -> CombatRoute | None:
    route_ids = {first_landmark_id, second_landmark_id}
    return next(
        (
            route
            for route in scene.routes
            if {
                route.source_landmark_id,
                route.destination_landmark_id,
            } == route_ids
        ),
        None,
    )


def path_cost(
    scene: CombatScene,
    path: tuple[str, ...],
) -> int:
    total = 0
    for source_id, destination_id in zip(path, path[1:]):
        route = route_between(
            scene,
            source_id,
            destination_id,
        )
        if route is None:
            raise ValueError(
                "Combat route changed while movement was resolved."
            )
        total += route.movement_cost
    return total


def shortest_path(
    scene: CombatScene,
    start_landmark_id: str,
    destination_landmark_id: str,
) -> tuple[str, ...] | None:
    if start_landmark_id == destination_landmark_id:
        return (start_landmark_id,)

    neighbours: dict[str, list[tuple[str, int]]] = {}
    for route in scene.routes:
        if route.blocked:
            continue
        neighbours.setdefault(
            route.source_landmark_id,
            [],
        ).append(
            (route.destination_landmark_id, route.movement_cost)
        )
        neighbours.setdefault(
            route.destination_landmark_id,
            [],
        ).append(
            (route.source_landmark_id, route.movement_cost)
        )

    queue: list[tuple[int, str, tuple[str, ...]]] = [
        (0, start_landmark_id, (start_landmark_id,))
    ]
    best_cost: dict[str, int] = {}

    while queue:
        cost, landmark_id, path = heapq.heappop(queue)
        if (
            landmark_id in best_cost
            and best_cost[landmark_id] <= cost
        ):
            continue

        best_cost[landmark_id] = cost
        if landmark_id == destination_landmark_id:
            return path

        for neighbour_id, route_cost in neighbours.get(
            landmark_id,
            (),
        ):
            next_cost = cost + route_cost
            if best_cost.get(
                neighbour_id,
                next_cost + 1,
            ) <= next_cost:
                continue
            heapq.heappush(
                queue,
                (
                    next_cost,
                    neighbour_id,
                    (*path, neighbour_id),
                ),
            )

    return None


def tactical_distance(
    scene: CombatScene,
    first: CombatantState,
    second: CombatantState,
) -> int | None:
    """Return shortest unblocked tactical distance between two combatants."""
    if same_combat_position(first, second):
        return 0

    def endpoint_options(
        combatant: CombatantState,
    ) -> list[tuple[str, int]]:
        if not combatant.is_between_landmarks:
            return [(combatant.landmark_id, 0)]

        source_id = combatant.route_source_landmark_id
        destination_id = combatant.route_destination_landmark_id
        assert source_id is not None
        assert destination_id is not None
        route = route_between(scene, source_id, destination_id)
        if route is None or route.blocked:
            return []
        return [
            (source_id, combatant.route_progress),
            (
                destination_id,
                combatant.route_cost - combatant.route_progress,
            ),
        ]

    candidates: list[int] = []

    if first.is_between_landmarks and second.is_between_landmarks:
        first_ids = {
            first.route_source_landmark_id,
            first.route_destination_landmark_id,
        }
        second_ids = {
            second.route_source_landmark_id,
            second.route_destination_landmark_id,
        }
        if first_ids == second_ids and first.route_cost == second.route_cost:
            source_id = first.route_source_landmark_id
            destination_id = first.route_destination_landmark_id
            assert source_id is not None
            assert destination_id is not None
            route = route_between(scene, source_id, destination_id)
            if route is not None and not route.blocked:
                canonical_start = min(source_id, destination_id)
                first_progress = (
                    first.route_progress
                    if first.route_source_landmark_id == canonical_start
                    else first.route_cost - first.route_progress
                )
                second_progress = (
                    second.route_progress
                    if second.route_source_landmark_id == canonical_start
                    else second.route_cost - second.route_progress
                )
                candidates.append(abs(first_progress - second_progress))

    for first_endpoint, first_partial in endpoint_options(first):
        for second_endpoint, second_partial in endpoint_options(second):
            path = shortest_path(
                scene,
                first_endpoint,
                second_endpoint,
            )
            if path is None:
                continue
            candidates.append(
                first_partial
                + path_cost(scene, path)
                + second_partial
            )

    return min(candidates) if candidates else None


def movement_legs(
    scene: CombatScene,
    combatant: CombatantState,
    destination_landmark_id: str,
) -> list[tuple[str, str, CombatRoute, int]]:
    def build_path_legs(
        path: tuple[str, ...],
    ) -> list[tuple[str, str, CombatRoute, int]]:
        result: list[tuple[str, str, CombatRoute, int]] = []
        for source_id, destination_id in zip(path, path[1:]):
            route = route_between(
                scene,
                source_id,
                destination_id,
            )
            if route is None:
                raise ValueError(
                    "Combat route changed while movement was resolved."
                )
            result.append(
                (source_id, destination_id, route, 0)
            )
        return result

    if not combatant.is_between_landmarks:
        path = shortest_path(
            scene,
            combatant.landmark_id,
            destination_landmark_id,
        )
        if path is None:
            raise ValueError(
                f"No unblocked route reaches landmark "
                f"'{destination_landmark_id}'."
            )
        return build_path_legs(path)

    source_id = combatant.route_source_landmark_id
    route_destination_id = combatant.route_destination_landmark_id
    assert source_id is not None
    assert route_destination_id is not None

    current_route = route_between(
        scene,
        source_id,
        route_destination_id,
    )
    if current_route is None:
        raise ValueError(
            "The route under this combatant no longer exists."
        )

    candidates: list[
        tuple[int, list[tuple[str, str, CombatRoute, int]]]
    ] = []

    path_from_destination = shortest_path(
        scene,
        route_destination_id,
        destination_landmark_id,
    )
    if path_from_destination is not None:
        candidates.append(
            (
                combatant.route_cost
                - combatant.route_progress
                + path_cost(
                    scene,
                    path_from_destination,
                ),
                [
                    (
                        source_id,
                        route_destination_id,
                        current_route,
                        combatant.route_progress,
                    ),
                    *build_path_legs(path_from_destination),
                ],
            )
        )

    path_from_source = shortest_path(
        scene,
        source_id,
        destination_landmark_id,
    )
    if path_from_source is not None:
        candidates.append(
            (
                combatant.route_progress
                + path_cost(
                    scene,
                    path_from_source,
                ),
                [
                    (
                        route_destination_id,
                        source_id,
                        current_route,
                        combatant.route_cost
                        - combatant.route_progress,
                    ),
                    *build_path_legs(path_from_source),
                ],
            )
        )

    if not candidates:
        raise ValueError(
            f"No unblocked route reaches landmark "
            f"'{destination_landmark_id}'."
        )

    candidates.sort(key=lambda candidate: candidate[0])
    return candidates[0][1]
