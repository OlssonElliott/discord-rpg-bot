'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
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
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Eye,
  Flag,
  RefreshCw,
  Route,
  ScrollText,
  Shield,
  Skull,
  Swords,
  Trash2,
  Users,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
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
} from './api';

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
    obstacle: string,
    blocked: boolean,
  ) => Promise<boolean>;
  onDeleteLandmark: (landmarkId: string) => Promise<boolean>;
  onDeleteConnection: (
    sourceId: string,
    destinationId: string,
  ) => Promise<boolean>;
};

const SAFE_FALLBACK_POSITIONS = [
  { x: 0.12, y: 0.18 },
  { x: 0.80, y: 0.18 },
  { x: 0.12, y: 0.82 },
  { x: 0.80, y: 0.82 },
  { x: 0.12, y: 0.34 },
  { x: 0.80, y: 0.34 },
  { x: 0.12, y: 0.66 },
  { x: 0.80, y: 0.66 },
  { x: 0.32, y: 0.34 },
  { x: 0.60, y: 0.34 },
  { x: 0.32, y: 0.66 },
  { x: 0.60, y: 0.66 },
];

function fallbackPosition(index: number) {
  if (index === 0) return { x: 0.5, y: 0.5 };
  return SAFE_FALLBACK_POSITIONS[
    (index - 1) % SAFE_FALLBACK_POSITIONS.length
  ];
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

function combatantKey(combatant: CombatantData) {
  return `${combatant.kind}:${combatant.source_id}`;
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
            className={[
              'combat-token',
              `combat-token--${combatant.kind}`,
              combatant.is_current_turn ? 'combat-token--current' : '',
            ].filter(Boolean).join(' ')}
          >
            {combatant.kind === 'character' ? <Users size={12} /> : <Skull size={12} />}
            {combatant.name}
            {combatant.is_current_turn && <small>TURN</small>}
            {!combatant.is_current_turn && combatant.relation !== 'at' && (
              <small>{combatant.relation}</small>
            )}
          </span>
        ))}
      </div>
    </article>
  );
}

const combatNodeTypes = { landmark: CombatLandmarkNode };

function combatNodes(
  scene: CombatSceneData,
  selectedLandmarkId: string | null,
): Node<CombatLandmarkNodeData>[] {
  return scene.landmarks.map((landmark, index) => {
    const fallback = fallbackPosition(index);
    const x = landmark.x ?? fallback.x;
    const y = landmark.y ?? fallback.y;
    return {
      id: landmark.id,
      type: 'landmark',
      position: {
        x: x * COMBAT_LAYOUT_WIDTH,
        y: y * COMBAT_LAYOUT_HEIGHT,
      },
      selected: landmark.id === selectedLandmarkId,
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
  selectedRouteId: string | null,
): Edge[] {
  const positions = new globalThis.Map(
    nodes.map((node) => [node.id, node.position]),
  );
  return scene.routes.map((route) => {
    const id = routeKey(
      route.source_landmark_id,
      route.destination_landmark_id,
    );
    return {
      id,
      source: route.source_landmark_id,
      target: route.destination_landmark_id,
      ...connectionHandles(
        positions.get(route.source_landmark_id),
        positions.get(route.destination_landmark_id),
      ),
      type: 'straight',
      label: route.blocked ? `${route.distance} · blocked` : route.distance,
      selected: id === selectedRouteId,
      className: route.blocked
        ? 'combat-connection-edge combat-connection-edge--blocked'
        : 'combat-connection-edge',
    };
  });
}

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

function label(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function CombatantInspectDialog({
  open,
  data,
  loading,
  error,
  onOpenChange,
}: {
  open: boolean;
  data: CombatantInspectData | null;
  loading: boolean;
  error: string;
  onOpenChange: (open: boolean) => void;
}) {
  const hpLabel = (
    data?.hp == null || data.max_hp == null
      ? 'HP unknown'
      : `${data.hp} / ${data.max_hp} HP`
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="combat-inspect-dialog sm:max-w-[760px]">
        <DialogHeader>
          <DialogTitle>{data?.name || 'Combatant inspector'}</DialogTitle>
          <DialogDescription>
            Read-only combat reference for stats, equipment and inventory.
          </DialogDescription>
        </DialogHeader>

        {loading && <p className="combat-inspect-loading">Loading combatant…</p>}
        {error && <p className="combat-inspect-error">{error}</p>}

        {data && !loading && (
          <div className="combat-inspect-content">
            <div className="combat-inspect-summary">
              <div>
                <small>{data.kind}</small>
                <strong>{hpLabel}</strong>
              </div>
              <Badge variant="outline">{label(data.status)}</Badge>
              {data.stance && <Badge variant="outline">{label(data.stance)}</Badge>}
              {data.race && <Badge variant="outline">{data.race}</Badge>}
            </div>

            {data.description && (
              <p className="combat-inspect-description">{data.description}</p>
            )}

            <section className="combat-inspect-section">
              <h3>Attributes</h3>
              <div className="combat-inspect-stats">
                {Object.entries(data.attributes).map(([name, value]) => (
                  <div key={name}>
                    <small>{label(name)}</small>
                    <strong>{value}</strong>
                  </div>
                ))}
                {!Object.keys(data.attributes).length && (
                  <p className="muted-row">No structured attributes available.</p>
                )}
              </div>
            </section>

            {data.enemy && (
              <section className="combat-inspect-section">
                <h3>Combat profile</h3>
                <div className="combat-inspect-stats">
                  <div><small>Difficulty</small><strong>{data.enemy.difficulty_level}</strong></div>
                  <div><small>Armor</small><strong>{data.enemy.armor}</strong></div>
                  <div><small>Magic resistance</small><strong>{data.enemy.magical_resistance}</strong></div>
                  <div><small>Attack DC</small><strong>{data.enemy.attack_dc}</strong></div>
                  <div><small>Defense DC</small><strong>{data.enemy.defense_dc}</strong></div>
                  <div><small>Damage</small><strong>{data.enemy.damage}</strong></div>
                </div>
                <dl className="combat-inspect-details">
                  <div><dt>Attack profile</dt><dd>{data.enemy.attack_profile}</dd></div>
                  {data.enemy.special_ability && (
                    <div><dt>Special ability</dt><dd>{data.enemy.special_ability}</dd></div>
                  )}
                  <div><dt>Typical behaviour</dt><dd>{data.enemy.typical_behaviour}</dd></div>
                </dl>
              </section>
            )}

            {!!Object.keys(data.skills).length && (
              <section className="combat-inspect-section">
                <h3>Skills</h3>
                <div className="combat-inspect-stats">
                  {Object.entries(data.skills).map(([name, value]) => (
                    <div key={name}>
                      <small>{label(name)}</small>
                      <strong>{value}</strong>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="combat-inspect-section">
              <h3>Equipment</h3>
              <div className="combat-inspect-list">
                {data.equipment.map((item) => (
                  <div key={`${item.slot}:${item.id}`}>
                    <span>
                      <small>{label(item.slot || '')}</small>
                      <strong>{item.name}</strong>
                    </span>
                  </div>
                ))}
                {!data.equipment.length && <p className="muted-row">Nothing equipped.</p>}
              </div>
            </section>

            <section className="combat-inspect-section">
              <h3>Inventory</h3>
              <div className="combat-inspect-list">
                {data.inventory.map((item) => (
                  <div key={item.id}>
                    <span>
                      <strong>{item.name}</strong>
                      {item.equipped_slot && <small>{label(item.equipped_slot)}</small>}
                    </span>
                    <Badge variant="outline">×{item.quantity ?? 1}</Badge>
                  </div>
                ))}
                {!data.inventory.length && <p className="muted-row">Inventory is empty.</p>}
              </div>
            </section>

            {data.wallet && (
              <section className="combat-inspect-wallet">
                <span>{data.wallet.copper} copper</span>
                <span>{data.wallet.silver} silver</span>
                <span>{data.wallet.gold} gold</span>
              </section>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function CombatantEditor({
  combatant,
  scene,
  busy,
  selected,
  onMove,
  onInspect,
  onRemoveEnemy,
  onSetInitiative,
}: {
  combatant: CombatantData;
  scene: CombatSceneData;
  busy: boolean;
  selected: boolean;
  onMove: (
    combatant: CombatantData,
    landmarkId: string,
    relation: Relation,
  ) => Promise<boolean>;
  onInspect: (combatant: CombatantData) => void;
  onRemoveEnemy: (enemyId: string) => Promise<boolean>;
  onSetInitiative: (
    combatant: CombatantData,
    initiativeScore: number,
  ) => Promise<boolean>;
}) {
  const [landmarkId, setLandmarkId] = useState(combatant.landmark_id);
  const [relation, setRelation] = useState<Relation>(combatant.relation);
  const [initiativeScore, setInitiativeScore] = useState(combatant.initiative_score);

  useEffect(() => {
    setLandmarkId(combatant.landmark_id);
    setRelation(combatant.relation);
    setInitiativeScore(combatant.initiative_score);
  }, [
    combatant.initiative_score,
    combatant.landmark_id,
    combatant.relation,
  ]);

  return (
    <div
      className={[
        'combatant-editor',
        combatant.is_current_turn ? 'combatant-editor--current' : '',
        selected ? 'combatant-editor--selected' : '',
      ].filter(Boolean).join(' ')}
    >
      <div className="combatant-editor__name">
        {combatant.kind === 'character' ? <Users size={15} /> : <Skull size={15} />}
        <span>{combatant.name}</span>
        {combatant.is_current_turn && <Badge>Current turn</Badge>}
        <Badge variant="outline">Init {combatant.initiative_score}</Badge>
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
      <div className="combatant-editor__initiative">
        <span>
          Initiative
          <small>d20 {combatant.initiative_roll}</small>
        </span>
        <Input
          type="number"
          value={initiativeScore}
          onChange={(event) => setInitiativeScore(Number(event.target.value))}
        />
        <Button
          size="sm"
          variant="outline"
          disabled={
            busy
            || !Number.isInteger(initiativeScore)
            || initiativeScore === combatant.initiative_score
          }
          onClick={() => void onSetInitiative(combatant, initiativeScore)}
        >
          Set
        </Button>
      </div>
      <div className="combatant-editor__actions">
        <Button
          size="sm"
          variant="outline"
          onClick={() => onInspect(combatant)}
        >
          <Eye /> Inspect
        </Button>
        {combatant.kind === 'enemy' && (
          <Button
            className="combatant-editor__remove"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => void onRemoveEnemy(combatant.source_id)}
          >
            <Trash2 /> Remove
          </Button>
        )}
      </div>
    </div>
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
  onMoveCombatant,
  onAddEnemy,
  onRemoveEnemy,
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
  const [routeObstacle, setRouteObstacle] = useState('');
  const [routeBlocked, setRouteBlocked] = useState(false);
  const [enemyTemplateId, setEnemyTemplateId] = useState('');
  const [enemyLandmarkId, setEnemyLandmarkId] = useState('room:center');
  const [enemyQuantity, setEnemyQuantity] = useState(1);
  const [selectionOpen, setSelectionOpen] = useState(true);
  const [connectionsOpen, setConnectionsOpen] = useState(true);
  const [addEnemyOpen, setAddEnemyOpen] = useState(false);
  const [combatantsOpen, setCombatantsOpen] = useState(true);
  const [combatLogOpen, setCombatLogOpen] = useState(false);
  const [selectedCombatantKey, setSelectedCombatantKey] = useState<string | null>(null);
  const [inspectOpen, setInspectOpen] = useState(false);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [inspectError, setInspectError] = useState('');
  const [inspectData, setInspectData] = useState<CombatantInspectData | null>(null);

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
    setNodes(nextNodes);
    setEdges(combatEdges(scene, nextNodes, selectedRouteId));
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
  }, [
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
    setRouteObstacle(route.obstacle || '');
    setRouteBlocked(route.blocked);
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
        setSelectedLandmarkId(null);
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
    )
    : null;
  const selectedRouteDestination = selectedRoute
    ? scene.landmarks.find(
      (landmark) => landmark.id === selectedRoute.destination_landmark_id,
    )
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
        <div className="combat-initiative">
          <div className="combat-initiative__heading">
            <div>
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
        <div className="combat-board">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={combatNodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_, node) => selectLandmark(node.id)}
            onNodeDragStop={saveLandmarkPosition}
            onConnect={connectNodes}
            onEdgeClick={(_, edge) => selectRoute(edge.source, edge.target)}
            onPaneClick={() => {
              setSelectedLandmarkId(null);
              setSelectedRouteId(null);
            }}
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
          {selectedLandmark ? (
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
              {selectedLandmark.feature_type === 'custom' && (
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={busy}
                  onClick={() => void onDeleteLandmark(selectedLandmark.id).then(
                    (removed) => {
                      if (removed) setSelectedLandmarkId(null);
                    },
                  )}
                >
                  <Trash2 /> Remove landmark
                </Button>
              )}
            </div>
          ) : selectedRoute ? (
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
              <label htmlFor="combat-route-distance">Distance</label>
              <NativeSelect
                id="combat-route-distance"
                value={routeDistance}
                onChange={(event) => setRouteDistance(event.target.value as Distance)}
              >
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
              <div className="combat-connection-actions">
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
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy}
                  onClick={() => void onDeleteConnection(
                    selectedRoute.source_landmark_id,
                    selectedRoute.destination_landmark_id,
                  ).then((removed) => {
                    if (removed) setSelectedRouteId(null);
                  })}
                >
                  <Trash2 /> Remove
                </Button>
              </div>
            </div>
          ) : (
            <p className="combat-selection-description">
              Select a landmark or connection to inspect it. Drag between landmark
              handles to create a new close connection.
            </p>
          )}
        </CollapsibleCombatSection>

        <CollapsibleCombatSection
          open={connectionsOpen}
          onToggle={() => setConnectionsOpen((open) => !open)}
          title={<><Route size={15} /> Connections</>}
          summary={String(scene.routes.length)}
        >
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
                  onClick={() => selectRoute(
                    route.source_landmark_id,
                    route.destination_landmark_id,
                  )}
                >
                  <strong>{source?.name || route.source_landmark_id}</strong>
                  <span>↔</span>
                  <strong>{destination?.name || route.destination_landmark_id}</strong>
                  <Badge variant="outline">{route.distance}</Badge>
                  {route.obstacle && <small>{route.obstacle}</small>}
                  {route.blocked && <CircleAlert size={14} />}
                </button>
              );
            })}
            {!scene.routes.length && (
              <p className="muted-row">No landmark connections yet.</p>
            )}
          </div>
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
            <label>
              Quantity
              <Input
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
