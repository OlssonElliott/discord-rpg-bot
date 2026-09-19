'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Background,
  ConnectionMode,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
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
  CombatLandmarkData,
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

const COMBAT_LAYOUT_WIDTH = 1000;
const COMBAT_LAYOUT_HEIGHT = 700;

type CombatLandmarkNodeData = {
  landmark: CombatLandmarkData;
  combatants: CombatantData[];
} & Record<string, unknown>;

type CardinalHandle = 'top' | 'right' | 'bottom' | 'left';

function routeKey(sourceId: string, destinationId: string) {
  return [sourceId, destinationId].sort().join('::');
}

function connectionHandles(
  source: { x: number; y: number } | undefined,
  target: { x: number; y: number } | undefined,
): { sourceHandle?: CardinalHandle; targetHandle?: CardinalHandle } {
  if (!source || !target) return {};
  const horizontal = Math.abs(target.x - source.x) > Math.abs(target.y - source.y);
  if (horizontal) {
    return target.x >= source.x
      ? { sourceHandle: 'right', targetHandle: 'left' }
      : { sourceHandle: 'left', targetHandle: 'right' };
  }
  return target.y >= source.y
    ? { sourceHandle: 'bottom', targetHandle: 'top' }
    : { sourceHandle: 'top', targetHandle: 'bottom' };
}

function CombatLandmarkNode({
  data,
  selected,
}: NodeProps<Node<CombatLandmarkNodeData>>) {
  const { landmark, combatants } = data;
  const kind = landmark.synthetic
    ? 'Anchor'
    : landmark.feature_type === 'door'
      ? 'Door'
      : 'Landmark';

  return (
    <article
      className={[
        'combat-landmark-node',
        landmark.synthetic ? 'combat-landmark-node--synthetic' : '',
        landmark.feature_type === 'door' ? 'combat-landmark-node--door' : '',
        selected ? 'combat-landmark-node--selected' : '',
      ].filter(Boolean).join(' ')}
    >
      <Handle id="top" type="source" position={Position.Top} />
      <Handle id="right" type="source" position={Position.Right} />
      <Handle id="bottom" type="source" position={Position.Bottom} />
      <Handle id="left" type="source" position={Position.Left} />
      <div className="combat-landmark-node__eyebrow">{kind}</div>
      <div className="combat-landmark-node__title">
        <Flag size={14} />
        <strong>{landmark.name}</strong>
      </div>
      {landmark.feature_type && landmark.feature_type !== 'door' && (
        <span className="combat-landmark-node__type">{landmark.feature_type}</span>
      )}
      {landmark.source_connection_id && (
        <span className="combat-landmark-node__type">linked room exit</span>
      )}
      <div className="combat-landmark-node__occupants">
        {combatants.map((combatant) => (
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
    </article>
  );
}

const combatNodeTypes = { landmark: CombatLandmarkNode };

function combatNodes(scene: CombatSceneData): Node<CombatLandmarkNodeData>[] {
  return scene.landmarks.map((landmark, index) => {
    const fallback = fallbackPosition(index, scene.landmarks.length);
    const x = landmark.x ?? fallback.x;
    const y = landmark.y ?? fallback.y;
    return {
      id: landmark.id,
      type: 'landmark',
      position: {
        x: x * COMBAT_LAYOUT_WIDTH,
        y: y * COMBAT_LAYOUT_HEIGHT,
      },
      data: {
        landmark,
        combatants: scene.combatants.filter(
          (combatant) => combatant.landmark_id === landmark.id,
        ),
      },
    };
  });
}

function combatEdges(
  scene: CombatSceneData,
  nodes: Node<CombatLandmarkNodeData>[],
): Edge[] {
  const positions = new globalThis.Map(
    nodes.map((node) => [node.id, node.position]),
  );
  return scene.routes.map((route) => ({
    id: routeKey(route.source_landmark_id, route.destination_landmark_id),
    source: route.source_landmark_id,
    target: route.destination_landmark_id,
    ...connectionHandles(
      positions.get(route.source_landmark_id),
      positions.get(route.destination_landmark_id),
    ),
    type: 'straight',
    label: route.blocked ? `${route.distance} · blocked` : route.distance,
    className: route.blocked
      ? 'combat-connection-edge combat-connection-edge--blocked'
      : 'combat-connection-edge',
  }));
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
  const [startRoomId, setStartRoomId] = useState(preferredRoomId || rooms[0]?.id || '');
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CombatLandmarkNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
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

  useEffect(() => {
    if (!scene) {
      setNodes([]);
      setEdges([]);
      setSelectedRouteId(null);
      return;
    }
    const nextNodes = combatNodes(scene);
    setNodes(nextNodes);
    setEdges(combatEdges(scene, nextNodes));
    if (
      selectedRouteId
      && !scene.routes.some(
        (route) => routeKey(
          route.source_landmark_id,
          route.destination_landmark_id,
        ) === selectedRouteId,
      )
    ) {
      setSelectedRouteId(null);
    }
  }, [scene, selectedRouteId, setEdges, setNodes]);

  const selectRoute = useCallback((sourceId: string, destinationId: string) => {
    if (!scene) return;
    const key = routeKey(sourceId, destinationId);
    const route = scene.routes.find(
      (item) => routeKey(
        item.source_landmark_id,
        item.destination_landmark_id,
      ) === key,
    );
    if (!route) return;
    setSelectedRouteId(key);
    setRouteSource(route.source_landmark_id);
    setRouteDestination(route.destination_landmark_id);
    setRouteDistance(route.distance);
    setRouteObstacle(route.obstacle || '');
    setRouteBlocked(route.blocked);
  }, [scene]);

  const connectNodes = useCallback((candidate: Connection) => {
    if (
      !scene
      || busy
      || !candidate.source
      || !candidate.target
      || candidate.source === candidate.target
    ) {
      return;
    }
    const existing = scene.routes.find(
      (route) => routeKey(
        route.source_landmark_id,
        route.destination_landmark_id,
      ) === routeKey(candidate.source!, candidate.target!),
    );
    if (existing) {
      selectRoute(existing.source_landmark_id, existing.destination_landmark_id);
      return;
    }

    setRouteSource(candidate.source);
    setRouteDestination(candidate.target);
    setRouteDistance('close');
    setRouteObstacle('');
    setRouteBlocked(false);
    void onConnectLandmarks(
      candidate.source,
      candidate.target,
      'close',
      '',
      false,
    ).then((saved) => {
      if (saved) {
        setSelectedRouteId(routeKey(candidate.source!, candidate.target!));
      }
    });
  }, [busy, onConnectLandmarks, scene, selectRoute]);

  const saveLandmarkPosition = useCallback(
    (_event: unknown, node: Node<CombatLandmarkNodeData>) => {
      void onPositionLandmark(
        node.id,
        clamp(node.position.x / COMBAT_LAYOUT_WIDTH),
        clamp(node.position.y / COMBAT_LAYOUT_HEIGHT),
      );
    },
    [onPositionLandmark],
  );

  if (!scene) {
    return (
      <section className="combat-empty-workspace">
        <div className="combat-empty-card">
          <Swords size={30} />
          <p className="kicker">Combat workspace</p>
          <h2>No active combat</h2>
          <p>
            Start from a location. Its room features and doors become persistent
            combat landmarks and everyone currently in the room joins the scene.
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
        <div className="combat-board">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={combatNodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeDragStop={saveLandmarkPosition}
            onConnect={connectNodes}
            onEdgeClick={(_, edge) => selectRoute(edge.source, edge.target)}
            onPaneClick={() => setSelectedRouteId(null)}
            connectionMode={ConnectionMode.Loose}
            nodesDraggable={!busy}
            nodesConnectable={!busy}
            fitView
            minZoom={0.35}
            maxZoom={1.8}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#334155" gap={28} size={1} />
            <MiniMap
              pannable
              zoomable
              nodeColor="#d39a4a"
              maskColor="rgba(8, 15, 26, 0.72)"
            />
            <Controls showInteractive={false} />
          </ReactFlow>
          <div className="combat-board__hint">
            Drag landmarks to arrange · Drag a handle to connect · Click a connection to edit
          </div>
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
          <h3><Route size={15} /> Connection</h3>
          <p className="combat-connection-help">
            Drag between landmark handles to create a close connection. Click an
            existing connection on the map to edit its distance, obstacle or state.
          </p>
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
            Connection is blocked
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
            Save connection
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
