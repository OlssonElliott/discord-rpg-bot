'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CircleAlert,
  Flag,
  RefreshCw,
  Route,
  Shield,
  Skull,
  Swords,
  Users,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type {
  CombatSceneData,
  CombatantData,
  RoomData,
} from './api';

type Relation = CombatantData['relation'];
type Distance = 'close' | 'far' | 'distant';

type CombatWorkspaceProps = {
  scene: CombatSceneData | null;
  rooms: RoomData[];
  preferredRoomId: string | null;
  busy: boolean;
  onStart: (roomId: string) => Promise<boolean>;
  onEnd: () => Promise<boolean>;
  onRefresh: () => Promise<void>;
  onPositionLandmark: (landmarkId: string, x: number, y: number) => Promise<boolean>;
  onMoveCombatant: (
    combatant: CombatantData,
    landmarkId: string,
    relation: Relation,
  ) => Promise<boolean>;
  onConnectLandmarks: (
    sourceId: string,
    destinationId: string,
    distance: Distance,
    obstacle: string,
    blocked: boolean,
  ) => Promise<boolean>;
};

function fallbackPosition(index: number, count: number) {
  if (index === 0) return { x: 0.5, y: 0.5 };
  const ringCount = Math.max(1, count - 1);
  const angle = ((index - 1) / ringCount) * Math.PI * 2 - Math.PI / 2;
  return {
    x: 0.5 + Math.cos(angle) * 0.34,
    y: 0.5 + Math.sin(angle) * 0.32,
  };
}

function clamp(value: number) {
  return Math.min(0.94, Math.max(0.06, value));
}

function CombatantEditor({
  combatant,
  scene,
  busy,
  onMove,
}: {
  combatant: CombatantData;
  scene: CombatSceneData;
  busy: boolean;
  onMove: (
    combatant: CombatantData,
    landmarkId: string,
    relation: Relation,
  ) => Promise<boolean>;
}) {
  const [landmarkId, setLandmarkId] = useState(combatant.landmark_id);
  const [relation, setRelation] = useState<Relation>(combatant.relation);

  useEffect(() => {
    setLandmarkId(combatant.landmark_id);
    setRelation(combatant.relation);
  }, [combatant.landmark_id, combatant.relation]);

  return (
    <div className="combatant-editor">
      <div className="combatant-editor__name">
        {combatant.kind === 'character' ? <Users size={15} /> : <Skull size={15} />}
        <span>{combatant.name}</span>
        <Badge variant="outline">{combatant.kind}</Badge>
      </div>
      <NativeSelect value={landmarkId} onChange={(event) => setLandmarkId(event.target.value)}>
        {scene.landmarks.map((landmark) => (
          <NativeSelectOption key={landmark.id} value={landmark.id}>
            {landmark.name}
          </NativeSelectOption>
        ))}
      </NativeSelect>
      <NativeSelect
        value={relation}
        onChange={(event) => setRelation(event.target.value as Relation)}
      >
        <NativeSelectOption value="at">At</NativeSelectOption>
        <NativeSelectOption value="beside">Beside</NativeSelectOption>
        <NativeSelectOption value="behind">Behind</NativeSelectOption>
        <NativeSelectOption value="on">On</NativeSelectOption>
        <NativeSelectOption value="inside">Inside</NativeSelectOption>
      </NativeSelect>
      <Button
        size="sm"
        variant="outline"
        disabled={
          busy
          || (landmarkId === combatant.landmark_id && relation === combatant.relation)
        }
        onClick={() => void onMove(combatant, landmarkId, relation)}
      >
        Move
      </Button>
    </div>
  );
}

export function CombatWorkspace({
  scene,
  rooms,
  preferredRoomId,
  busy,
  onStart,
  onEnd,
  onRefresh,
  onPositionLandmark,
  onMoveCombatant,
  onConnectLandmarks,
}: CombatWorkspaceProps) {
  const board = useRef<HTMLDivElement>(null);
  const [startRoomId, setStartRoomId] = useState(preferredRoomId || rooms[0]?.id || '');
  const [routeSource, setRouteSource] = useState('');
  const [routeDestination, setRouteDestination] = useState('');
  const [routeDistance, setRouteDistance] = useState<Distance>('close');
  const [routeObstacle, setRouteObstacle] = useState('');
  const [routeBlocked, setRouteBlocked] = useState(false);

  useEffect(() => {
    if (scene) return;
    const preferred = rooms.find((room) => room.id === preferredRoomId)?.id;
    if (preferred) {
      setStartRoomId(preferred);
    } else if (!rooms.some((room) => room.id === startRoomId)) {
      setStartRoomId(rooms[0]?.id || '');
    }
  }, [preferredRoomId, rooms, scene, startRoomId]);

  useEffect(() => {
    if (!scene?.landmarks.length) return;
    const first = scene.landmarks[0]?.id || '';
    const second = scene.landmarks[1]?.id || first;
    if (!scene.landmarks.some((item) => item.id === routeSource)) {
      setRouteSource(first);
    }
    if (!scene.landmarks.some((item) => item.id === routeDestination)) {
      setRouteDestination(second);
    }
  }, [routeDestination, routeSource, scene]);

  const positions = useMemo(() => {
    const result = new Map<string, { x: number; y: number }>();
    if (!scene) return result;
    scene.landmarks.forEach((landmark, index) => {
      const fallback = fallbackPosition(index, scene.landmarks.length);
      result.set(landmark.id, {
        x: landmark.x ?? fallback.x,
        y: landmark.y ?? fallback.y,
      });
    });
    return result;
  }, [scene]);

  const combatantsByLandmark = useMemo(() => {
    const result = new Map<string, CombatantData[]>();
    for (const combatant of scene?.combatants ?? []) {
      result.set(
        combatant.landmark_id,
        [...(result.get(combatant.landmark_id) ?? []), combatant],
      );
    }
    return result;
  }, [scene]);

  if (!scene) {
    return (
      <section className="combat-empty-workspace">
        <div className="combat-empty-card">
          <Swords size={30} />
          <p className="kicker">Combat workspace</p>
          <h2>No active combat</h2>
          <p>
            Start from a location. Its room features become persistent combat
            landmarks and everyone currently in the room joins the scene.
          </p>
          <label htmlFor="combat-start-room">Location</label>
          <NativeSelect
            id="combat-start-room"
            value={startRoomId}
            onChange={(event) => setStartRoomId(event.target.value)}
          >
            {rooms.map((room) => (
              <NativeSelectOption key={room.id} value={room.id}>
                {room.name} · {room.counts.players} players · {room.counts.enemies} enemies
              </NativeSelectOption>
            ))}
          </NativeSelect>
          <Button
            disabled={!startRoomId || busy}
            onClick={() => void onStart(startRoomId)}
          >
            <Swords /> {busy ? 'Starting…' : 'Start combat'}
          </Button>
          {!rooms.length && (
            <p className="combat-empty-note">
              Select an area containing at least one location.
            </p>
          )}
        </div>
      </section>
    );
  }

  const canSaveRoute = (
    routeSource
    && routeDestination
    && routeSource !== routeDestination
  );

  return (
    <section className="combat-workspace">
      <div className="combat-stage">
        <div className="combat-stage__heading">
          <div>
            <p className="kicker">Active encounter</p>
            <h2>{scene.room_name}</h2>
            <span>Scene #{scene.id} · drag landmarks to arrange the shared scene</span>
          </div>
          <Button variant="outline" size="sm" disabled={busy} onClick={() => void onRefresh()}>
            <RefreshCw /> Refresh
          </Button>
        </div>
        <div ref={board} className="combat-board">
          <svg className="combat-route-lines" aria-hidden="true">
            {scene.routes.map((route) => {
              const source = positions.get(route.source_landmark_id);
              const destination = positions.get(route.destination_landmark_id);
              if (!source || !destination) return null;
              return (
                <line
                  key={`${route.source_landmark_id}:${route.destination_landmark_id}`}
                  x1={`${source.x * 100}%`}
                  y1={`${source.y * 100}%`}
                  x2={`${destination.x * 100}%`}
                  y2={`${destination.y * 100}%`}
                  className={route.blocked ? 'combat-route-line combat-route-line--blocked' : 'combat-route-line'}
                />
              );
            })}
          </svg>
          {scene.landmarks.map((landmark) => {
            const position = positions.get(landmark.id) || { x: 0.5, y: 0.5 };
            const occupants = combatantsByLandmark.get(landmark.id) ?? [];
            return (
              <div
                key={landmark.id}
                className={`combat-landmark${landmark.synthetic ? ' combat-landmark--synthetic' : ''}`}
                style={{
                  left: `${position.x * 100}%`,
                  top: `${position.y * 100}%`,
                }}
                draggable={!busy}
                onDragEnd={(event) => {
                  const bounds = board.current?.getBoundingClientRect();
                  if (!bounds || event.clientX === 0 || event.clientY === 0) return;
                  void onPositionLandmark(
                    landmark.id,
                    clamp((event.clientX - bounds.left) / bounds.width),
                    clamp((event.clientY - bounds.top) / bounds.height),
                  );
                }}
              >
                <div className="combat-landmark__title">
                  <Flag size={14} />
                  <strong>{landmark.name}</strong>
                </div>
                {landmark.feature_type && (
                  <span className="combat-landmark__type">{landmark.feature_type}</span>
                )}
                <div className="combat-landmark__occupants">
                  {occupants.map((combatant) => (
                    <span
                      key={`${combatant.kind}:${combatant.source_id}`}
                      className={`combat-token combat-token--${combatant.kind}`}
                    >
                      {combatant.kind === 'character' ? <Users size={12} /> : <Skull size={12} />}
                      {combatant.name}
                      {combatant.relation !== 'at' && <small>{combatant.relation}</small>}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
          <div className="combat-board__hint">Drag a landmark to persist its visual position.</div>
        </div>
      </div>

      <aside className="combat-control-panel">
        <div className="combat-control-panel__heading">
          <div>
            <p className="kicker">DM controls</p>
            <h2>{scene.combatants.length} combatants</h2>
          </div>
          <Badge>Active</Badge>
        </div>

        <section className="combat-control-section">
          <h3><Shield size={15} /> Combatants</h3>
          <div className="combatant-editor-list">
            {scene.combatants.map((combatant) => (
              <CombatantEditor
                key={`${combatant.kind}:${combatant.source_id}`}
                combatant={combatant}
                scene={scene}
                busy={busy}
                onMove={onMoveCombatant}
              />
            ))}
            {!scene.combatants.length && <p className="muted-row">No combatants are in this scene.</p>}
          </div>
        </section>

        <section className="combat-control-section">
          <h3><Route size={15} /> Landmark route</h3>
          <label htmlFor="combat-route-source">From</label>
          <NativeSelect id="combat-route-source" value={routeSource} onChange={(event) => setRouteSource(event.target.value)}>
            {scene.landmarks.map((landmark) => (
              <NativeSelectOption key={landmark.id} value={landmark.id}>{landmark.name}</NativeSelectOption>
            ))}
          </NativeSelect>
          <label htmlFor="combat-route-destination">To</label>
          <NativeSelect id="combat-route-destination" value={routeDestination} onChange={(event) => setRouteDestination(event.target.value)}>
            {scene.landmarks.map((landmark) => (
              <NativeSelectOption key={landmark.id} value={landmark.id}>{landmark.name}</NativeSelectOption>
            ))}
          </NativeSelect>
          <label htmlFor="combat-route-distance">Distance</label>
          <NativeSelect id="combat-route-distance" value={routeDistance} onChange={(event) => setRouteDistance(event.target.value as Distance)}>
            <NativeSelectOption value="close">Close</NativeSelectOption>
            <NativeSelectOption value="far">Far</NativeSelectOption>
            <NativeSelectOption value="distant">Distant</NativeSelectOption>
          </NativeSelect>
          <label htmlFor="combat-route-obstacle">Obstacle or risk</label>
          <Input
            id="combat-route-obstacle"
            placeholder="Rubble, fire, open ground…"
            value={routeObstacle}
            onChange={(event) => setRouteObstacle(event.target.value)}
          />
          <label className="combat-checkbox">
            <input
              type="checkbox"
              checked={routeBlocked}
              onChange={(event) => setRouteBlocked(event.target.checked)}
            />
            Route is blocked
          </label>
          <Button
            size="sm"
            disabled={!canSaveRoute || busy}
            onClick={() => void onConnectLandmarks(
              routeSource,
              routeDestination,
              routeDistance,
              routeObstacle,
              routeBlocked,
            )}
          >
            Save route
          </Button>
          <div className="combat-route-list">
            {scene.routes.map((route) => {
              const source = scene.landmarks.find((item) => item.id === route.source_landmark_id);
              const destination = scene.landmarks.find((item) => item.id === route.destination_landmark_id);
              return (
                <p key={`${route.source_landmark_id}:${route.destination_landmark_id}`}>
                  <strong>{source?.name || route.source_landmark_id}</strong>
                  <span>↔</span>
                  <strong>{destination?.name || route.destination_landmark_id}</strong>
                  <Badge variant="outline">{route.distance}</Badge>
                  {route.obstacle && <small>{route.obstacle}</small>}
                  {route.blocked && <CircleAlert size={14} />}
                </p>
              );
            })}
          </div>
        </section>

        <Button
          className="combat-end"
          variant="destructive"
          disabled={busy}
          onClick={() => void onEnd()}
        >
          End combat
        </Button>
      </aside>
    </section>
  );
}
