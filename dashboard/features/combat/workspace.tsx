'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import {
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from '@xyflow/react';
import {
  ChevronDown,
  ChevronRight,
  Flag,
  RefreshCw,
  Route,
  ScrollText,
  Shield,
  Skull,
  Swords,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import {
  api,
  type CombatantInspectData,
  CombatLandmarkData,
  type CombatSceneData,
  type CombatantData,
  type EnemyTemplateData,
  type RoomData,
} from '@/lib/api';

import {
  COMBAT_LAYOUT_HEIGHT,
  COMBAT_LAYOUT_WIDTH,
  clamp,
  combatantKey,
  combatEdges,
  combatNodes,
  routeKey,
  type CombatLandmarkNodeData,
} from './combat-graph';
import { CombatantEditor } from './combatant-editor';
import { CombatantInspectDialog } from './combatant-inspect-dialog';
import { CombatMap } from './combat-map';
import { ConnectionsPanel } from './connections-panel';
import { SelectionPanel } from './selection-panel';

type Relation = CombatantData['relation'];
type Distance = 'close' | 'far' | 'distant';

type CombatWorkspaceProps = {
  scene: CombatSceneData | null;
  rooms: RoomData[];
  enemyTemplates: EnemyTemplateData[];
  preferredRoomId: string | null;
  busy: boolean;
  onStart: (roomId: string) => Promise<boolean>;
  onEnd: () => Promise<boolean>;
  onRefresh: () => Promise<void>;
  onPositionLandmark: (landmarkId: string, x: number, y: number) => Promise<boolean>;
  onSetLandmarkCover: (
    landmarkId: string,
    cover: CombatLandmarkData['cover'],
  ) => Promise<boolean>;
  onAutoConnectLandmark: (landmarkId: string) => Promise<boolean>;
  onDisconnectLandmarkRoutes: (landmarkId: string) => Promise<boolean>;
  onAutoConnectAll: () => Promise<boolean>;
  onDisconnectAllRoutes: () => Promise<boolean>;
  onMoveCombatant: (
    combatant: CombatantData,
    landmarkId: string,
    relation: Relation,
  ) => Promise<boolean>;
  onAddEnemy: (
    templateId: string,
    landmarkId: string,
    quantity: number,
  ) => Promise<boolean>;
  onRemoveEnemy: (enemyId: string) => Promise<boolean>;
  onAttack: (
    attacker: CombatantData,
    targetId: string,
  ) => Promise<boolean>;
  onNextTurn: () => Promise<boolean>;
  onPreviousTurn: () => Promise<boolean>;
  onSetInitiative: (
    combatant: CombatantData,
    initiativeScore: number,
  ) => Promise<boolean>;
  onConnectLandmarks: (
    sourceId: string,
    destinationId: string,
    distance: Distance,
    terrain: 'normal' | 'difficult',
    baseBlocked: boolean,
  ) => Promise<boolean>;
  onDeleteLandmark: (landmarkId: string) => Promise<boolean>;
  onDeleteConnection: (
    sourceId: string,
    destinationId: string,
  ) => Promise<boolean>;
};

function CollapsibleCombatSection({
  open,
  onToggle,
  title,
  summary,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  title: ReactNode;
  summary?: string;
  children: ReactNode;
}) {
  return (
    <section className="combat-control-section">
      <button
        type="button"
        className="combat-section-toggle"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="combat-section-toggle__title">{title}</span>
        {summary && <Badge variant="outline">{summary}</Badge>}
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {open && <div className="combat-section-body">{children}</div>}
    </section>
  );
}

export function CombatWorkspace({
  scene,
  rooms,
  enemyTemplates,
  preferredRoomId,
  busy,
  onStart,
  onEnd,
  onRefresh,
  onPositionLandmark,
  onSetLandmarkCover,
  onAutoConnectLandmark,
  onDisconnectLandmarkRoutes,
  onAutoConnectAll,
  onDisconnectAllRoutes,
  onMoveCombatant,
  onAddEnemy,
  onRemoveEnemy,
  onAttack,
  onNextTurn,
  onPreviousTurn,
  onSetInitiative,
  onConnectLandmarks,
  onDeleteLandmark,
  onDeleteConnection,
}: CombatWorkspaceProps) {
  const [startRoomId, setStartRoomId] = useState(preferredRoomId || rooms[0]?.id || '');
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CombatLandmarkNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedLandmarkId, setSelectedLandmarkId] = useState<string | null>(null);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [routeSource, setRouteSource] = useState('');
  const [routeDestination, setRouteDestination] = useState('');
  const [routeDistance, setRouteDistance] = useState<Distance>('close');
  const [routeTerrain, setRouteTerrain] = useState<'normal' | 'difficult'>('normal');
  const [routeBaseBlocked, setRouteBaseBlocked] = useState(false);
  const [enemyTemplateId, setEnemyTemplateId] = useState('');
  const [enemyLandmarkId, setEnemyLandmarkId] = useState('room:center');
  const [enemyQuantity, setEnemyQuantity] = useState(1);
  const [selectionOpen, setSelectionOpen] = useState(false);
  const [connectionsOpen, setConnectionsOpen] = useState(false);
  const [addEnemyOpen, setAddEnemyOpen] = useState(false);
  const [combatantsOpen, setCombatantsOpen] = useState(false);
  const [combatLogOpen, setCombatLogOpen] = useState(false);
  const [selectedCombatantKey, setSelectedCombatantKey] = useState<string | null>(null);
  const [inspectOpen, setInspectOpen] = useState(false);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [inspectError, setInspectError] = useState('');
  const [inspectData, setInspectData] = useState<CombatantInspectData | null>(null);
  const [draggingLandmarkId, setDraggingLandmarkId] = useState<string | null>(null);

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
    if (!scene) {
      setEnemyLandmarkId('room:center');
      return;
    }
    if (!scene.landmarks.some((landmark) => landmark.id === enemyLandmarkId)) {
      setEnemyLandmarkId(
        scene.landmarks.find((landmark) => landmark.id === 'room:center')?.id
          || scene.landmarks[0]?.id
          || '',
      );
    }
  }, [enemyLandmarkId, scene]);

  useEffect(() => {
    const ignoreBenignResizeObserverError = (event: ErrorEvent) => {
      if (
        event.message === 'ResizeObserver loop completed with undelivered notifications.'
        || event.message === 'ResizeObserver loop limit exceeded'
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    };
    window.addEventListener(
      'error',
      ignoreBenignResizeObserverError,
      true,
    );
    return () => {
      window.removeEventListener(
        'error',
        ignoreBenignResizeObserverError,
        true,
      );
    };
  }, []);

  useEffect(() => {
    if (!scene) {
      setNodes([]);
      setEdges([]);
      setSelectedLandmarkId(null);
      setSelectedRouteId(null);
      setSelectedCombatantKey(null);
      setInspectOpen(false);
      return;
    }
    const nextNodes = combatNodes(scene, selectedLandmarkId);
    const frame = window.requestAnimationFrame(() => {
      if (draggingLandmarkId) return;
      setNodes(nextNodes);
      setEdges(combatEdges(scene, nextNodes, selectedRouteId));
    });
    if (
      selectedLandmarkId
      && !scene.landmarks.some((landmark) => landmark.id === selectedLandmarkId)
    ) {
      setSelectedLandmarkId(null);
    }
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
    if (
      selectedCombatantKey
      && !scene.combatants.some(
        (combatant) => combatantKey(combatant) === selectedCombatantKey,
      )
    ) {
      setSelectedCombatantKey(null);
    }
    return () => window.cancelAnimationFrame(frame);
  }, [
    draggingLandmarkId,
    scene,
    selectedCombatantKey,
    selectedLandmarkId,
    selectedRouteId,
    setEdges,
    setNodes,
  ]);

  const selectRoute = useCallback((sourceId: string, destinationId: string) => {
    if (!scene) return;
    setSelectionOpen(true);
    const key = routeKey(sourceId, destinationId);
    const route = scene.routes.find(
      (item) => routeKey(
        item.source_landmark_id,
        item.destination_landmark_id,
      ) === key,
    );
    if (!route) return;
    setSelectedLandmarkId(null);
    setSelectedRouteId(key);
    setRouteSource(route.source_landmark_id);
    setRouteDestination(route.destination_landmark_id);
    setRouteDistance(route.distance);
    setRouteTerrain(route.terrain);
    setRouteBaseBlocked(route.base_blocked);
  }, [scene]);

  const selectLandmark = useCallback((landmarkId: string) => {
    setSelectionOpen(true);
    setSelectedRouteId(null);
    setSelectedLandmarkId(landmarkId);
  }, []);

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
    setRouteTerrain('normal');
    setRouteBaseBlocked(false);
    void onConnectLandmarks(
      candidate.source,
      candidate.target,
      'close',
      'normal',
      false,
    ).then((saved) => {
      if (saved) {
        setSelectedLandmarkId(null);
        setSelectedRouteId(routeKey(candidate.source!, candidate.target!));
      }
    });
  }, [busy, onConnectLandmarks, scene, selectRoute]);

  const saveLandmarkPosition = useCallback(
    async (_event: unknown, node: Node<CombatLandmarkNodeData>) => {
      await onPositionLandmark(
        node.id,
        clamp(node.position.x / COMBAT_LAYOUT_WIDTH),
        clamp(node.position.y / COMBAT_LAYOUT_HEIGHT),
      );
    },
    [onPositionLandmark],
  );

  const inspectCombatant = useCallback(async (combatant: CombatantData) => {
    setSelectedCombatantKey(combatantKey(combatant));
    setCombatantsOpen(true);
    setInspectOpen(true);
    setInspectLoading(true);
    setInspectError('');
    setInspectData(null);
    try {
      const data = await api<CombatantInspectData>(
        `/combat/combatants/${combatant.kind}/${encodeURIComponent(combatant.source_id)}/inspect`,
      );
      setInspectData(data);
    } catch (requestError) {
      setInspectError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not inspect this combatant.',
      );
    } finally {
      setInspectLoading(false);
    }
  }, []);

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
  const selectedLandmark = scene.landmarks.find(
    (landmark) => landmark.id === selectedLandmarkId,
  ) ?? null;
  const selectedRoute = scene.routes.find(
    (route) => routeKey(
      route.source_landmark_id,
      route.destination_landmark_id,
    ) === selectedRouteId,
  ) ?? null;
  const selectedRouteSource = selectedRoute
    ? scene.landmarks.find(
      (landmark) => landmark.id === selectedRoute.source_landmark_id,
    ) ?? null
    : null;
  const selectedRouteDestination = selectedRoute
    ? scene.landmarks.find(
      (landmark) => landmark.id === selectedRoute.destination_landmark_id,
    ) ?? null
    : null;
  const orderedCombatants = scene.combatants;
  const currentCombatant = orderedCombatants.find(
    (combatant) => combatant.is_current_turn,
  ) ?? null;
  const pendingCombatants = orderedCombatants.filter(
    (combatant) => (
      !combatant.is_current_turn
      && !combatant.acted_this_round
    ),
  );
  const actedCombatants = orderedCombatants.filter(
    (combatant) => combatant.acted_this_round,
  );
  const upcomingCombatants = currentCombatant
    ? [currentCombatant, ...pendingCombatants, ...actedCombatants]
    : [...pendingCombatants, ...actedCombatants];

  return (
    <section className="combat-workspace">
      <div className="combat-stage">
        <div className="combat-initiative">
          <div className="combat-initiative__heading">
            <div className="combat-initiative__context">
              <strong className="combat-initiative__room">{scene.room_name}</strong>
              <span className="combat-initiative__round">
                Round {scene.round_number}
              </span>
              <strong>
                {currentCombatant
                  ? `${currentCombatant.name}'s turn`
                  : 'No current turn'}
              </strong>
            </div>
            <div className="combat-initiative__controls">
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => void onRefresh()}
              >
                <RefreshCw /> Refresh
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy || !scene.combatants.length}
                onClick={() => void onPreviousTurn()}
              >
                Previous
              </Button>
              <Button
                size="sm"
                disabled={busy || !scene.combatants.length}
                onClick={() => void onNextTurn()}
              >
                Next turn
              </Button>
            </div>
          </div>
          <div className="combat-initiative__track">
            {upcomingCombatants.map((combatant, index) => (
              <button
                type="button"
                key={`${combatant.kind}:${combatant.source_id}`}
                className={[
                  'combat-initiative__entry',
                  combatant.is_current_turn
                    ? 'combat-initiative__entry--current'
                    : '',
                  combatant.acted_this_round
                    ? 'combat-initiative__entry--acted'
                    : '',
                  selectedCombatantKey === combatantKey(combatant)
                    ? 'combat-initiative__entry--selected'
                    : '',
                ].filter(Boolean).join(' ')}
                onClick={() => {
                  setSelectedCombatantKey(combatantKey(combatant));
                  setCombatantsOpen(true);
                }}
              >
                <small>
                  {combatant.is_current_turn
                    ? 'NOW'
                    : combatant.acted_this_round
                      ? 'DONE'
                      : index === 1
                        ? 'NEXT'
                        : 'UPCOMING'}
                </small>
                <span>{combatant.name}</span>
                <strong>{combatant.initiative_score}</strong>
              </button>
            ))}
            {!upcomingCombatants.length && (
              <span className="combat-initiative__empty">
                Add a combatant to begin initiative.
              </span>
            )}
          </div>
        </div>
        <CombatMap
          nodes={nodes}
          edges={edges}
          busy={busy}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={selectLandmark}
          onNodeDragStart={(nodeId) => setDraggingLandmarkId(nodeId)}
          onNodeDragStop={async (node) => {
            try {
              await saveLandmarkPosition(undefined, node);
            } finally {
              setDraggingLandmarkId(null);
            }
          }}
          onAutoConnectAll={onAutoConnectAll}
          onConnect={connectNodes}
          onEdgeClick={selectRoute}
          onPaneClick={() => {
            setSelectedLandmarkId(null);
            setSelectedRouteId(null);
          }}
        />
      </div>

      <aside className="combat-control-panel">
        <div className="combat-control-panel__heading">
          <div>
            <p className="kicker">DM controls</p>
            <h2>{scene.combatants.length} combatants</h2>
          </div>
          <Badge>Active</Badge>
        </div>

        <CollapsibleCombatSection
          open={selectionOpen}
          onToggle={() => setSelectionOpen((open) => !open)}
          title={
            selectedLandmark
              ? <><Flag size={15} /> Selected landmark</>
              : selectedRoute
                ? <><Route size={15} /> Selected connection</>
                : <><Flag size={15} /> Selection</>
          }
          summary={
            selectedLandmark?.name
            || (
              selectedRoute
                ? `${selectedRouteSource?.name || 'Route'} ↔ ${selectedRouteDestination?.name || 'Route'}`
                : 'None'
            )
          }
        >
          <SelectionPanel
            selectedLandmark={selectedLandmark}
            selectedRoute={selectedRoute}
            selectedRouteSource={selectedRouteSource}
            selectedRouteDestination={selectedRouteDestination}
            busy={busy}
            routeSource={routeSource}
            routeDestination={routeDestination}
            routeDistance={routeDistance}
            routeTerrain={routeTerrain}
            routeBaseBlocked={routeBaseBlocked}
            canSaveRoute={Boolean(canSaveRoute)}
            onSetRouteDistance={setRouteDistance}
            onSetRouteTerrain={setRouteTerrain}
            onSetRouteBaseBlocked={setRouteBaseBlocked}
            onSetLandmarkCover={onSetLandmarkCover}
            onAutoConnectLandmark={onAutoConnectLandmark}
            onDisconnectLandmarkRoutes={onDisconnectLandmarkRoutes}
            onDeleteLandmark={onDeleteLandmark}
            onConnectLandmarks={onConnectLandmarks}
            onDeleteConnection={onDeleteConnection}
            onClearLandmarkSelection={() => setSelectedLandmarkId(null)}
            onClearRouteSelection={() => setSelectedRouteId(null)}
          />
        </CollapsibleCombatSection>

        <CollapsibleCombatSection
          open={connectionsOpen}
          onToggle={() => setConnectionsOpen((open) => !open)}
          title={<><Route size={15} /> Connections</>}
          summary={String(scene.routes.length)}
        >
          <ConnectionsPanel
            scene={scene}
            selectedRouteId={selectedRouteId}
            busy={busy}
            onSelectRoute={selectRoute}
            onAutoConnectAll={onAutoConnectAll}
            onDisconnectAllRoutes={onDisconnectAllRoutes}
            onClearRouteSelection={() => setSelectedRouteId(null)}
          />
        </CollapsibleCombatSection>

        <CollapsibleCombatSection
          open={addEnemyOpen}
          onToggle={() => setAddEnemyOpen((open) => !open)}
          title={<><Skull size={15} /> Add enemy</>}
        >
          <div className="combat-enemy-adder">
            <label>
              Enemy type
              <NativeSelect
                value={enemyTemplateId}
                onChange={(event) => setEnemyTemplateId(event.target.value)}
              >
                <NativeSelectOption value="">Choose enemy…</NativeSelectOption>
                {enemyTemplates.map((template) => (
                  <NativeSelectOption key={template.id} value={template.id}>
                    {template.name} · difficulty {template.difficulty_level}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </label>
            <label>
              Spawn at
              <NativeSelect
                value={enemyLandmarkId}
                onChange={(event) => setEnemyLandmarkId(event.target.value)}
              >
                {scene.landmarks.map((landmark) => (
                  <NativeSelectOption key={landmark.id} value={landmark.id}>
                    {landmark.name}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </label>
            <label htmlFor="combat-enemy-quantity">
              Quantity
              <Input
                id="combat-enemy-quantity"
                type="number"
                min={1}
                max={20}
                value={enemyQuantity}
                onChange={(event) => setEnemyQuantity(Number(event.target.value))}
              />
            </label>
            <Button
              size="sm"
              disabled={
                busy
                || !enemyTemplateId
                || !enemyLandmarkId
                || !Number.isInteger(enemyQuantity)
                || enemyQuantity < 1
                || enemyQuantity > 20
              }
              onClick={async () => {
                if (await onAddEnemy(
                  enemyTemplateId,
                  enemyLandmarkId,
                  enemyQuantity,
                )) {
                  setEnemyQuantity(1);
                }
              }}
            >
              <Skull /> Add {enemyQuantity > 1 ? `${enemyQuantity} enemies` : 'enemy'}
            </Button>
            {!enemyTemplates.length && (
              <p className="muted-row">
                No enemy types are available. Create one in the Enemy library.
              </p>
            )}
          </div>
        </CollapsibleCombatSection>

        <CollapsibleCombatSection
          open={combatantsOpen}
          onToggle={() => setCombatantsOpen((open) => !open)}
          title={<><Shield size={15} /> Combatants</>}
          summary={String(scene.combatants.length)}
        >
          <div className="combatant-editor-list">
            {scene.combatants.map((combatant) => (
              <CombatantEditor
                key={combatantKey(combatant)}
                combatant={combatant}
                scene={scene}
                busy={busy}
                selected={selectedCombatantKey === combatantKey(combatant)}
                onMove={onMoveCombatant}
                onInspect={(selected) => void inspectCombatant(selected)}
                onRemoveEnemy={onRemoveEnemy}
                onAttack={onAttack}
                onSetInitiative={onSetInitiative}
              />
            ))}
            {!scene.combatants.length && (
              <p className="muted-row">No combatants are in this scene.</p>
            )}
          </div>
        </CollapsibleCombatSection>

        <CollapsibleCombatSection
          open={combatLogOpen}
          onToggle={() => setCombatLogOpen((open) => !open)}
          title={<><ScrollText size={15} /> Combat log</>}
          summary={String(scene.log_entries.length)}
        >
          <div className="combat-log-list">
            {[...scene.log_entries].reverse().map((entry) => (
              <article
                key={entry.id}
                className={`combat-log-entry combat-log-entry--${entry.event_type}`}
              >
                <div>
                  <Badge variant="outline">R{entry.round_number}</Badge>
                  <time dateTime={entry.created_at}>
                    {new Date(entry.created_at).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </time>
                </div>
                <p>{entry.message}</p>
              </article>
            ))}
            {!scene.log_entries.length && (
              <p className="muted-row">No combat events recorded yet.</p>
            )}
          </div>
        </CollapsibleCombatSection>

        <Button
          className="combat-end"
          variant="destructive"
          disabled={busy}
          onClick={() => {
            if (window.confirm('End this combat encounter?')) {
              void onEnd();
            }
          }}
        >
          End combat
        </Button>
      </aside>

      <CombatantInspectDialog
        open={inspectOpen}
        data={inspectData}
        loading={inspectLoading}
        error={inspectError}
        onOpenChange={setInspectOpen}
      />
    </section>
  );
}
