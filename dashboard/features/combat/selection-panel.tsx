'use client';

import { Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type {
  CombatLandmarkData,
  CombatRouteData,
} from '@/lib/api';

type Distance = CombatRouteData['distance'];
type Terrain = CombatRouteData['terrain'];

type SelectionPanelProps = {
  selectedLandmark: CombatLandmarkData | null;
  selectedRoute: CombatRouteData | null;
  selectedRouteSource: CombatLandmarkData | null;
  selectedRouteDestination: CombatLandmarkData | null;
  busy: boolean;
  routeSource: string;
  routeDestination: string;
  routeDistance: Distance;
  routeTerrain: Terrain;
  routeBaseBlocked: boolean;
  canSaveRoute: boolean;
  onSetRouteDistance: (distance: Distance) => void;
  onSetRouteTerrain: (terrain: Terrain) => void;
  onSetRouteBaseBlocked: (blocked: boolean) => void;
  onSetLandmarkCover: (
    landmarkId: string,
    cover: CombatLandmarkData['cover'],
  ) => Promise<boolean>;
  onAutoConnectLandmark: (landmarkId: string) => Promise<boolean>;
  onDisconnectLandmarkRoutes: (landmarkId: string) => Promise<boolean>;
  onDeleteLandmark: (landmarkId: string) => Promise<boolean>;
  onConnectLandmarks: (
    sourceId: string,
    destinationId: string,
    distance: Distance,
    terrain: Terrain,
    baseBlocked: boolean,
  ) => Promise<boolean>;
  onDeleteConnection: (
    sourceId: string,
    destinationId: string,
  ) => Promise<boolean>;
  onClearLandmarkSelection: () => void;
  onClearRouteSelection: () => void;
};

export function SelectionPanel({
  selectedLandmark,
  selectedRoute,
  selectedRouteSource,
  selectedRouteDestination,
  busy,
  routeSource,
  routeDestination,
  routeDistance,
  routeTerrain,
  routeBaseBlocked,
  canSaveRoute,
  onSetRouteDistance,
  onSetRouteTerrain,
  onSetRouteBaseBlocked,
  onSetLandmarkCover,
  onAutoConnectLandmark,
  onDisconnectLandmarkRoutes,
  onDeleteLandmark,
  onConnectLandmarks,
  onDeleteConnection,
  onClearLandmarkSelection,
  onClearRouteSelection,
}: SelectionPanelProps) {
  if (selectedLandmark) {
    return (
      <div className="combat-selection-section">
        <div className="combat-selection-title">
          <strong className="combat-selection-name">{selectedLandmark.name}</strong>
          <Badge variant="outline">
            {selectedLandmark.synthetic
              ? 'Anchor'
              : selectedLandmark.source_connection_id
                ? 'Door'
                : selectedLandmark.source_feature_id
                  ? selectedLandmark.feature_type || 'Room feature'
                  : 'Custom'}
          </Badge>
        </div>
        <p className="combat-selection-description">
          {selectedLandmark.description || 'No description.'}
        </p>
        {selectedLandmark.source_connection_id && (
          <p className="combat-selection-meta">Linked to the room exit.</p>
        )}
        {selectedLandmark.source_feature_id && (
          <p className="combat-selection-meta">Snapshot of a room feature.</p>
        )}
        <label htmlFor="combat-landmark-cover">Cover</label>
        <NativeSelect
          id="combat-landmark-cover"
          value={selectedLandmark.cover}
          disabled={busy || selectedLandmark.synthetic}
          onChange={(event) => void onSetLandmarkCover(
            selectedLandmark.id,
            event.target.value as CombatLandmarkData['cover'],
          )}
        >
          <NativeSelectOption value="none">None</NativeSelectOption>
          <NativeSelectOption value="half">Half</NativeSelectOption>
          <NativeSelectOption value="full">Full</NativeSelectOption>
        </NativeSelect>
        <div className="combat-connection-actions">
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => void onAutoConnectLandmark(selectedLandmark.id)}
          >
            Auto-connect
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={busy}
            onClick={() => void onDisconnectLandmarkRoutes(
              selectedLandmark.id,
            ).then((removed) => {
              if (removed) onClearRouteSelection();
            })}
          >
            Disconnect all
          </Button>
        </div>
        {selectedLandmark.synthetic && (
          <p className="combat-selection-meta">
            Room anchors are movement positions and cannot provide cover.
          </p>
        )}
        <Button
          variant="destructive"
          size="sm"
          disabled={busy}
          onClick={() => void onDeleteLandmark(selectedLandmark.id).then(
            (removed) => {
              if (removed) onClearLandmarkSelection();
            },
          )}
        >
          <Trash2 /> Remove landmark
        </Button>
      </div>
    );
  }

  if (selectedRoute) {
    return (
      <div className="combat-selection-section">
        <div className="combat-route-card">
          <strong>
            {selectedRouteSource?.name || selectedRoute.source_landmark_id}
          </strong>
          <span>↔</span>
          <strong>
            {selectedRouteDestination?.name || selectedRoute.destination_landmark_id}
          </strong>
        </div>
        <p className="combat-selection-meta">
          Movement cost: {selectedRoute.movement_cost}
        </p>
        <label htmlFor="combat-route-distance">Distance</label>
        <NativeSelect
          id="combat-route-distance"
          value={routeDistance}
          onChange={(event) => onSetRouteDistance(event.target.value as Distance)}
        >
          <NativeSelectOption value="close">Close</NativeSelectOption>
          <NativeSelectOption value="far">Far</NativeSelectOption>
          <NativeSelectOption value="distant">Distant</NativeSelectOption>
        </NativeSelect>
        <label htmlFor="combat-route-terrain">Terrain</label>
        <NativeSelect
          id="combat-route-terrain"
          value={routeTerrain}
          onChange={(event) => onSetRouteTerrain(event.target.value as Terrain)}
        >
          <NativeSelectOption value="normal">Normal</NativeSelectOption>
          <NativeSelectOption value="difficult">Difficult terrain</NativeSelectOption>
        </NativeSelect>
        <label className="combat-checkbox">
          <input
            type="checkbox"
            checked={routeBaseBlocked}
            onChange={(event) => onSetRouteBaseBlocked(event.target.checked)}
          />
          Base route is blocked
        </label>
        {selectedRoute.blocked && !selectedRoute.base_blocked && (
          <p className="combat-selection-meta">
            Currently blocked by an active effect.
          </p>
        )}
        {!!selectedRoute.effects.length && (
          <div className="combat-route-effects">
            <strong>Active effects</strong>
            {selectedRoute.effects.map((effect) => (
              <p key={effect.id} className="combat-selection-meta">
                {effect.name}
                {effect.blocks_movement ? ' · Blocks movement' : ''}
                {effect.movement_cost_modifier
                  ? ` · Move ${effect.movement_cost_modifier > 0 ? '+' : ''}${effect.movement_cost_modifier}`
                  : ''}
                {effect.remaining_rounds != null
                  ? ` · ${effect.remaining_rounds} rounds`
                  : ''}
              </p>
            ))}
          </div>
        )}
        <div className="combat-connection-actions">
          <Button
            size="sm"
            disabled={!canSaveRoute || busy}
            onClick={() => void onConnectLandmarks(
              routeSource,
              routeDestination,
              routeDistance,
              routeTerrain,
              routeBaseBlocked,
            )}
          >
            Save connection
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={busy}
            onClick={() => void onDeleteConnection(
              selectedRoute.source_landmark_id,
              selectedRoute.destination_landmark_id,
            ).then((removed) => {
              if (removed) onClearRouteSelection();
            })}
          >
            <Trash2 /> Remove
          </Button>
        </div>
      </div>
    );
  }

  return (
    <p className="combat-selection-description">
      Select a landmark or connection to inspect it. Drag between landmark
      handles to create a new close connection.
    </p>
  );
}
