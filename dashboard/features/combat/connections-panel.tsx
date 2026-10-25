'use client';

import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, CircleAlert } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { CombatSceneData } from '@/lib/api';

import { routeKey } from './combat-graph';

type ConnectionsPanelProps = {
  scene: CombatSceneData;
  selectedRouteId: string | null;
  busy: boolean;
  onSelectRoute: (sourceId: string, destinationId: string) => void;
  onAutoConnectAll: () => Promise<boolean>;
  onDisconnectAllRoutes: () => Promise<boolean>;
  onClearRouteSelection: () => void;
};

export function ConnectionsPanel({
  scene,
  selectedRouteId,
  busy,
  onSelectRoute,
  onAutoConnectAll,
  onDisconnectAllRoutes,
  onClearRouteSelection,
}: ConnectionsPanelProps) {
  const [openLandmarks, setOpenLandmarks] = useState<Set<string>>(
    () => new Set(),
  );

  const routeGroups = useMemo(
    () => scene.landmarks
      .map((landmark) => ({
        landmark,
        routes: scene.routes.filter(
          (route) => (
            route.source_landmark_id === landmark.id
            || route.destination_landmark_id === landmark.id
          ),
        ),
      }))
      .filter((group) => group.routes.length > 0)
      .sort((first, second) => (
        first.landmark.name.localeCompare(second.landmark.name)
      )),
    [scene.landmarks, scene.routes],
  );

  useEffect(() => {
    if (!selectedRouteId) return;
    const route = scene.routes.find(
      (candidate) => routeKey(
        candidate.source_landmark_id,
        candidate.destination_landmark_id,
      ) === selectedRouteId,
    );
    if (!route) return;
    setOpenLandmarks((current) => {
      const next = new Set(current);
      next.add(route.source_landmark_id);
      next.add(route.destination_landmark_id);
      return next;
    });
  }, [scene.routes, selectedRouteId]);

  const toggleLandmark = (landmarkId: string) => {
    setOpenLandmarks((current) => {
      const next = new Set(current);
      if (next.has(landmarkId)) {
        next.delete(landmarkId);
      } else {
        next.add(landmarkId);
      }
      return next;
    });
  };
  return (
    <>
      <div className="combat-connection-actions">
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => void onAutoConnectAll()}
        >
          Auto-connect all
        </Button>
        <Button
          size="sm"
          variant="destructive"
          disabled={busy || !scene.routes.length}
          onClick={() => {
            if (!window.confirm('Remove every combat connection?')) return;
            void onDisconnectAllRoutes().then((removed) => {
              if (removed) onClearRouteSelection();
            });
          }}
        >
          Disconnect all
        </Button>
      </div>
      <div className="combat-route-groups">
        {routeGroups.map(({ landmark, routes }) => {
          const open = openLandmarks.has(landmark.id);
          return (
            <section
              key={landmark.id}
              className="combat-route-group"
            >
              <button
                type="button"
                className="combat-route-group__toggle"
                aria-expanded={open}
                onClick={() => toggleLandmark(landmark.id)}
              >
                <span className="combat-route-group__name">
                  {landmark.name}
                </span>
                <Badge variant="outline">{routes.length}</Badge>
                {open
                  ? <ChevronDown size={15} />
                  : <ChevronRight size={15} />}
              </button>
              {open && (
                <div className="combat-route-list">
                  {routes
                    .slice()
                    .sort((first, second) => {
                      const firstOtherId = first.source_landmark_id === landmark.id
                        ? first.destination_landmark_id
                        : first.source_landmark_id;
                      const secondOtherId = second.source_landmark_id === landmark.id
                        ? second.destination_landmark_id
                        : second.source_landmark_id;
                      const firstName = scene.landmarks.find(
                        (item) => item.id === firstOtherId,
                      )?.name ?? firstOtherId;
                      const secondName = scene.landmarks.find(
                        (item) => item.id === secondOtherId,
                      )?.name ?? secondOtherId;
                      return firstName.localeCompare(secondName);
                    })
                    .map((route) => {
                      const id = routeKey(
                        route.source_landmark_id,
                        route.destination_landmark_id,
                      );
                      const otherId = route.source_landmark_id === landmark.id
                        ? route.destination_landmark_id
                        : route.source_landmark_id;
                      const other = scene.landmarks.find(
                        (item) => item.id === otherId,
                      );
                      return (
                        <button
                          type="button"
                          key={id}
                          className={id === selectedRouteId ? 'selected' : ''}
                          onClick={() => onSelectRoute(
                            route.source_landmark_id,
                            route.destination_landmark_id,
                          )}
                        >
                          <span className="combat-route-list__destination">
                            ↔ {other?.name || otherId}
                          </span>
                          <Badge variant="outline">{route.distance}</Badge>
                          <Badge variant="outline">
                            move {route.movement_cost}
                          </Badge>
                          {route.terrain !== 'normal' && (
                            <Badge variant="outline">{route.terrain}</Badge>
                          )}
                          {route.blocked && <CircleAlert size={14} />}
                        </button>
                      );
                    })}
                </div>
              )}
            </section>
          );
        })}
        {!scene.routes.length && (
          <p className="muted-row">No landmark connections yet.</p>
        )}
      </div>
    </>
  );
}
