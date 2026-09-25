'use client';

import { CircleAlert } from 'lucide-react';

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
      <div className="combat-route-list">
        {scene.routes.map((route) => {
          const source = scene.landmarks.find(
            (item) => item.id === route.source_landmark_id,
          );
          const destination = scene.landmarks.find(
            (item) => item.id === route.destination_landmark_id,
          );
          const id = routeKey(
            route.source_landmark_id,
            route.destination_landmark_id,
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
              <strong>{source?.name || route.source_landmark_id}</strong>
              <span>↔</span>
              <strong>{destination?.name || route.destination_landmark_id}</strong>
              <Badge variant="outline">{route.distance}</Badge>
              <Badge variant="outline">move {route.movement_cost}</Badge>
              {route.terrain !== 'normal' && (
                <Badge variant="outline">{route.terrain}</Badge>
              )}
              {route.blocked && <CircleAlert size={14} />}
            </button>
          );
        })}
        {!scene.routes.length && (
          <p className="muted-row">No landmark connections yet.</p>
        )}
      </div>
    </>
  );
}
