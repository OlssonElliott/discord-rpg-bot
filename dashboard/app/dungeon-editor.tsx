'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Image from 'next/image';
import {
  Background,
  ConnectionMode,
  Controls,
  Handle,
  MarkerType,
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
import '@xyflow/react/dist/style.css';
import {
  Box,
  CircleAlert,
  ImageIcon,
  Map,
  Plus,
  Save,
  Skull,
  Sparkles,
  Swords,
  Trash2,
  Upload,
  Users,
} from 'lucide-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { CombatWorkspace } from './combat-workspace';
import {
  api,
  apiAssetUrl,
  identifier,
  uploadRoomImage,
  type AreaGraphData,
  type AreaSummary,
  type CatalogItem,
  type CharacterSummary,
  type CombatSceneData,
  type CombatStateData,
  type ConnectionData,
  type EnemyTemplateData,
  type RoomData,
} from './api';

type RoomNodeData = RoomData & Record<string, unknown>;
type ContentKind = 'enemy' | 'item' | 'container';
type MapConnectionType = 'door' | 'hallway';
type DoorLockState = 'none' | 'unlocked' | 'locked' | 'broken';
type DoorState = 'closed' | 'open';
type TrapDamageType = 'physical' | 'fire' | 'cold' | 'lightning' | 'poison' | 'acid';
type TrapState = 'armed' | 'disarmed' | 'triggered';

type ContainerTypeValue =
  | 'wooden_chest'
  | 'reinforced_chest'
  | 'barrel'
  | 'crate'
  | 'shelf'
  | 'bookshelf'
  | 'corpse'
  | 'skeleton'
  | 'backpack'
  | 'hidden_compartment'
  | 'loose_floorboard'
  | 'other';

type ContainerTemplateData = {
  id: string;
  name: string;
  type: ContainerTypeValue;
  description: string;
  default_has_lock: boolean;
  default_is_locked: boolean;
  default_is_broken: boolean;
  default_unlock_difficulty: number | null;
  default_hidden: boolean;
  default_discovery_difficulty: number | null;
};

type RoomFeatureTemplateData = {
  id: string;
  name: string;
  description: string;
  feature_type: string;
};

type EnemyTemplateDraft = Omit<EnemyTemplateData, 'id'>;

type ContainerContentItem = {
  id: string;
  name: string;
  description: string | null;
  quantity: number;
};

type PlacedContainer = {
  id: string;
  room_id: string;
  template_id: string;
  name: string;
  type: ContainerTypeValue;
  description: string;
  has_lock: boolean;
  is_locked: boolean;
  is_broken: boolean;
  unlock_difficulty: number | null;
  hidden: boolean;
  discovery_difficulty: number | null;
  is_open: boolean;
  searched: boolean;
  item_count: number;
  contents: ContainerContentItem[];
};

type ContainerTemplateDraft = {
  name: string;
  type: ContainerTypeValue;
  description: string;
  lockState: DoorLockState;
  unlockDifficulty: number;
  hidden: boolean;
  discoveryDifficulty: number;
};

const CONTAINER_TYPES: { value: ContainerTypeValue; label: string }[] = [
  { value: 'wooden_chest', label: 'Wooden Chest' },
  { value: 'reinforced_chest', label: 'Reinforced Chest' },
  { value: 'barrel', label: 'Barrel' },
  { value: 'crate', label: 'Crate' },
  { value: 'shelf', label: 'Shelf' },
  { value: 'bookshelf', label: 'Bookshelf' },
  { value: 'corpse', label: 'Corpse' },
  { value: 'skeleton', label: 'Skeleton' },
  { value: 'backpack', label: 'Backpack' },
  { value: 'hidden_compartment', label: 'Hidden Compartment' },
  { value: 'loose_floorboard', label: 'Loose Floorboard' },
  { value: 'other', label: 'Other' },
];

const TRAP_DAMAGE_TYPES: { value: TrapDamageType; label: string }[] = [
  { value: 'physical', label: 'Physical' },
  { value: 'fire', label: 'Fire' },
  { value: 'cold', label: 'Cold' },
  { value: 'lightning', label: 'Lightning' },
  { value: 'poison', label: 'Poison' },
  { value: 'acid', label: 'Acid' },
];

function normalizedTrapDamageType(value: string | null): TrapDamageType {
  return TRAP_DAMAGE_TYPES.some((item) => item.value === value)
    ? value as TrapDamageType
    : 'physical';
}

function RoomNode({ data, selected }: NodeProps<Node<RoomNodeData>>) {
  return (
    <article className={`room-node ${selected ? 'room-node--selected' : ''}`}>
      <Handle id="top" type="source" position={Position.Top} />
      <Handle id="right" type="source" position={Position.Right} />
      <Handle id="bottom" type="source" position={Position.Bottom} />
      <Handle id="left" type="source" position={Position.Left} />
      <div className="room-node__eyebrow">Location</div>
      <h3>{data.name}</h3>
      <div className="room-node__stats" aria-label="Room contents">
        <span title="Players"><Users size={13} />{data.counts.players}</span>
        <span title="Enemies"><Skull size={13} />{data.counts.enemies}</span>
        <span title="Loose items"><Sparkles size={13} />{data.counts.items}</span>
        <span title="Containers"><Box size={13} />{data.counts.containers}</span>
      </div>
    </article>
  );
}

const nodeTypes = { room: RoomNode };

function graphNodes(graph: AreaGraphData): Node<RoomNodeData>[] {
  return graph.nodes.map((room) => ({
    id: room.id,
    type: 'room',
    position: room.position,
    data: room,
  }));
}

function edgeId(connection: ConnectionData): string {
  return connection.connection_id || `${connection.source_room_id}::${connection.exit_name}`;
}

type CardinalHandle = 'top' | 'right' | 'bottom' | 'left';

const EXIT_NAME_BY_HANDLE: Record<CardinalHandle, string> = {
  top: 'north',
  right: 'east',
  bottom: 'south',
  left: 'west',
};

function exitNameForHandle(handle: string | null | undefined): string {
  return handle && handle in EXIT_NAME_BY_HANDLE
    ? EXIT_NAME_BY_HANDLE[handle as CardinalHandle]
    : 'passage';
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

function graphEdges(graph: AreaGraphData): Edge[] {
  const positions = new globalThis.Map(
    graph.nodes.map((room) => [room.id, room.position]),
  );
  return graph.connections.map((connection) => {
    const handles = connectionHandles(
      positions.get(connection.source_room_id),
      positions.get(connection.destination_room_id),
    );
    return {
      id: edgeId(connection),
      source: connection.source_room_id,
      target: connection.destination_room_id,
      ...handles,
      label: connection.bidirectional && connection.return_exit_name
        ? `${connection.exit_name} ↔ ${connection.return_exit_name}`
        : connection.exit_name,
      markerStart: connection.bidirectional ? { type: MarkerType.ArrowClosed } : undefined,
      markerEnd: { type: MarkerType.ArrowClosed },
    };
  });
}

export function DungeonEditor() {
  const [workspaceMode, setWorkspaceMode] = useState<'locations' | 'combat'>('locations');
  const [combatScene, setCombatScene] = useState<CombatSceneData | null>(null);
  const [combatBusy, setCombatBusy] = useState(false);
  const [areas, setAreas] = useState<AreaSummary[]>([]);
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [catalogItems, setCatalogItems] = useState<CatalogItem[]>([]);
  const [areaId, setAreaId] = useState('');
  const [graph, setGraph] = useState<AreaGraphData | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<RoomNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [addRoomOpen, setAddRoomOpen] = useState(false);
  const [addCombatLandmarkOpen, setAddCombatLandmarkOpen] = useState(false);
  const [addAreaOpen, setAddAreaOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [contentKind, setContentKind] = useState<ContentKind | null>(null);
  const [itemLibraryOpen, setItemLibraryOpen] = useState(false);
  const [enemyLibraryOpen, setEnemyLibraryOpen] = useState(false);
  const [enemyTemplates, setEnemyTemplates] = useState<EnemyTemplateData[]>([]);
  const [enemyPlacementOpen, setEnemyPlacementOpen] = useState(false);
  const [featureLibraryOpen, setFeatureLibraryOpen] = useState(false);
  const [roomFeatureTemplates, setRoomFeatureTemplates] = useState<RoomFeatureTemplateData[]>([]);
  const [containerTemplates, setContainerTemplates] = useState<ContainerTemplateData[]>([]);
  const [containerPlacementOpen, setContainerPlacementOpen] = useState(false);
  const [editingContainerId, setEditingContainerId] = useState<string | null>(null);
  const [roomFeatureOpen, setRoomFeatureOpen] = useState(false);
  const [editingRoomFeature, setEditingRoomFeature] = useState<{
    id: string;
    room_id: string;
    name: string;
    description: string;
    feature_type: string;
  } | null>(null);

  const selectedRoom = useMemo(
    () => graph?.nodes.find((room) => room.id === selectedRoomId) ?? null,
    [graph, selectedRoomId],
  );
  const selectedConnection = useMemo(
    () => graph?.connections.find((item) => edgeId(item) === selectedEdgeId) ?? null,
    [graph, selectedEdgeId],
  );
  const selectedContainer = useMemo(
    () => (selectedRoom?.containers as PlacedContainer[] | undefined)
      ?.find((item) => item.id === editingContainerId) ?? null,
    [editingContainerId, selectedRoom],
  );

  const loadAreas = useCallback(async (preferredArea?: string) => {
    try {
      const result = await api<AreaSummary[]>('/areas');
      setAreas(result);
      setAreaId((current) => preferredArea || current || result[0]?.id || '');
      setError('');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load areas.');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadGraph = useCallback(async (requestedArea: string) => {
    if (!requestedArea) {
      setGraph(null);
      setNodes([]);
      setEdges([]);
      return;
    }
    try {
      const result = await api<AreaGraphData>(`/areas/${requestedArea}/graph`);
      setGraph(result);
      setNodes(graphNodes(result));
      setEdges(graphEdges(result));
      setSelectedRoomId((current) =>
        result.nodes.some((room) => room.id === current) ? current : result.nodes[0]?.id || null,
      );
      setSelectedEdgeId(null);
      setError('');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load the graph.');
    }
  }, [setEdges, setNodes]);

  const loadCharacters = useCallback(async () => {
    try {
      setCharacters(await api<CharacterSummary[]>('/characters'));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load characters.');
    }
  }, []);

  const loadCatalogItems = useCallback(async () => {
    try {
      setCatalogItems(await api<CatalogItem[]>('/items'));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load items.');
    }
  }, []);

  const loadContainerTemplates = useCallback(async () => {
    try {
      setContainerTemplates(await api<ContainerTemplateData[]>('/container-templates'));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load containers.');
    }
  }, []);

  const loadEnemyTemplates = useCallback(async () => {
    try {
      setEnemyTemplates(await api<EnemyTemplateData[]>('/enemy-templates'));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load enemies.');
    }
  }, []);

  const loadRoomFeatureTemplates = useCallback(async () => {
    try {
      setRoomFeatureTemplates(await api<RoomFeatureTemplateData[]>('/room-feature-templates'));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load room features.');
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadAreas();
      void loadCharacters();
      void loadCatalogItems();
      void loadContainerTemplates();
      void loadEnemyTemplates();
      void loadRoomFeatureTemplates();
    });
  }, [loadAreas, loadCatalogItems, loadCharacters, loadContainerTemplates, loadEnemyTemplates, loadRoomFeatureTemplates]);
  useEffect(() => {
    if (areaId) queueMicrotask(() => void loadGraph(areaId));
  }, [areaId, loadGraph]);

  const loadCombat = useCallback(async (quiet = false) => {
    try {
      const state = await api<CombatStateData>('/combat');
      setCombatScene(state.scene);
      if (!quiet) setError('');
    } catch (requestError) {
      if (!quiet) {
        setError(requestError instanceof Error ? requestError.message : 'Could not load combat.');
      }
    }
  }, []);

  const startCombat = useCallback(async (roomId: string) => {
    setCombatBusy(true);
    try {
      const state = await api<CombatStateData>('/combat', {
        method: 'POST',
        body: JSON.stringify({ room_id: roomId }),
      });
      setCombatScene(state.scene);
      setWorkspaceMode('combat');
      setNotice('Combat started');
      setError('');
      return true;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not start combat.');
      return false;
    } finally {
      setCombatBusy(false);
    }
  }, []);

  const endCombat = useCallback(async () => {
    setCombatBusy(true);
    try {
      const state = await api<CombatStateData>('/combat', { method: 'DELETE' });
      setCombatScene(state.scene);
      setNotice('Combat ended');
      setError('');
      return true;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not end combat.');
      return false;
    } finally {
      setCombatBusy(false);
    }
  }, []);

  const updateCombat = useCallback(async (
    path: string,
    init: RequestInit,
    message: string,
  ) => {
    setCombatBusy(true);
    try {
      const state = await api<CombatStateData>(path, init);
      setCombatScene(state.scene);
      setNotice(message);
      setError('');
      window.setTimeout(() => setNotice(''), 1400);
      return true;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Combat change was rejected.');
      return false;
    } finally {
      setCombatBusy(false);
    }
  }, []);

  useEffect(() => {
    if (workspaceMode !== 'combat') return;
    let cancelled = false;
    const refresh = async () => {
      if (cancelled || document.visibilityState === 'hidden') return;
      await loadCombat(true);
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [loadCombat, workspaceMode]);

  useEffect(() => {
    if (!areaId) return;
    let cancelled = false;
    let refreshing = false;

    const refreshLiveState = async () => {
      if (refreshing || document.visibilityState === 'hidden') return;
      refreshing = true;
      try {
        const [nextGraph, nextCharacters] = await Promise.all([
          api<AreaGraphData>(`/areas/${areaId}/graph`),
          api<CharacterSummary[]>('/characters'),
        ]);
        if (cancelled) return;
        setGraph(nextGraph);
        setCharacters(nextCharacters);
        const liveRooms = new globalThis.Map(
          nextGraph.nodes.map((room) => [room.id, room]),
        );
        setNodes((current) => current.map((node) => {
          const liveRoom = liveRooms.get(node.id);
          return liveRoom ? { ...node, data: liveRoom } : node;
        }));
      } catch {
        // Initial/manual loads surface errors; background synchronization stays quiet.
      } finally {
        refreshing = false;
      }
    };

    const interval = window.setInterval(() => void refreshLiveState(), 2000);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void refreshLiveState();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [areaId, setNodes]);

  const mutate = useCallback(async (action: () => Promise<unknown>, message: string) => {
    try {
      await action();
      await Promise.all([
        loadGraph(areaId),
        loadAreas(areaId),
        loadCharacters(),
        loadCatalogItems(),
        loadContainerTemplates(),
        loadEnemyTemplates(),
        loadRoomFeatureTemplates(),
      ]);
      setNotice(message);
      setError('');
      window.setTimeout(() => setNotice(''), 1800);
      return true;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The change was rejected.');
      return false;
    }
  }, [areaId, loadAreas, loadCatalogItems, loadCharacters, loadContainerTemplates, loadEnemyTemplates, loadGraph, loadRoomFeatureTemplates]);

  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool || !areaId) return;
    const lifecycle = new AbortController();
    const register = (tool: WebMCPTool) => {
      void Promise.resolve(
        context.registerTool(tool, { signal: lifecycle.signal }),
      ).catch(() => undefined);
    };
    register({
      name: 'create_location',
      title: 'Create location',
      description: 'Create a persisted room in the currently selected area and refresh the visible graph.',
      inputSchema: {
        type: 'object',
        properties: {
          name: { type: 'string', minLength: 1 },
          description: { type: 'string' },
        },
        required: ['name'],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      async execute(input) {
        if (!input || typeof input !== 'object' || !('name' in input) || typeof input.name !== 'string' || !input.name.trim()) {
          throw new Error('A non-empty location name is required.');
        }
        const description = 'description' in input && typeof input.description === 'string' ? input.description : '';
        const id = identifier(input.name);
        const offset = nodes.length * 36;
        const ok = await mutate(
          () => api(`/areas/${areaId}/rooms`, { method: 'POST', body: JSON.stringify({ id, name: input.name, description, x: 180 + offset, y: 140 + offset }) }),
          'Location created',
        );
        if (!ok) throw new Error('The backend rejected the location.');
        return { id, area_id: areaId };
      },
    });
    register({
      name: 'connect_locations',
      title: 'Connect locations',
      description: 'Connect two rooms with a two-way passage by default.',
      inputSchema: {
        type: 'object',
        properties: {
          source_room_id: { type: 'string', minLength: 1 },
          destination_room_id: { type: 'string', minLength: 1 },
          exit_name: { type: 'string', minLength: 1 },
          return_exit_name: { type: 'string', minLength: 1 },
          bidirectional: { type: 'boolean', default: true },
          connection_type: { type: 'string', enum: ['door', 'hallway'], default: 'hallway' },
          has_lock: { type: 'boolean', default: false },
          is_locked: { type: 'boolean', default: false },
          is_broken: { type: 'boolean', default: false },
          is_open: { type: 'boolean', default: false },
          unlock_difficulty: { type: 'integer', minimum: 1, maximum: 30, default: 10 },
          has_trap: { type: 'boolean', default: false },
          trap_state: { type: 'string', enum: ['armed', 'disarmed', 'triggered'], default: 'armed' },
          trap_detection_difficulty: { type: 'integer', minimum: 1, maximum: 30, default: 10 },
          trap_disarm_difficulty: { type: 'integer', minimum: 1, maximum: 30, default: 10 },
          trap_damage_type: { type: 'string', enum: ['physical', 'fire', 'cold', 'lightning', 'poison', 'acid'], default: 'physical' },
          trap_damage: { type: 'integer', minimum: 1, default: 1 },
        },
        required: ['source_room_id', 'destination_room_id', 'exit_name'],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      async execute(input) {
        if (!input || typeof input !== 'object') throw new Error('Connection input is required.');
        const values = input as Record<string, unknown>;
        for (const field of ['source_room_id', 'destination_room_id', 'exit_name']) {
          if (typeof values[field] !== 'string' || !values[field].trim()) {
            throw new Error(`${field} is required.`);
          }
        }
        const connectionType = values.connection_type === 'door' ? 'door' : 'hallway';
        const hasLock = connectionType === 'door' && values.has_lock === true;
        const isBroken = hasLock && values.is_broken === true;
        const isLocked = hasLock && !isBroken && values.is_locked === true;
        const isOpen = connectionType === 'door' && !isLocked && values.is_open === true;
        const hasTrap = values.has_trap === true;
        const payload = {
          ...values,
          connection_type: connectionType,
          has_lock: hasLock,
          is_locked: isLocked,
          is_broken: isBroken,
          is_open: isOpen,
          unlock_difficulty: isLocked && typeof values.unlock_difficulty === 'number'
            ? values.unlock_difficulty
            : isLocked ? 10 : null,
          has_trap: hasTrap,
          trap_state: hasTrap && typeof values.trap_state === 'string' ? values.trap_state : hasTrap ? 'armed' : null,
          trap_detection_difficulty: hasTrap && typeof values.trap_detection_difficulty === 'number' ? values.trap_detection_difficulty : hasTrap ? 10 : null,
          trap_disarm_difficulty: hasTrap && typeof values.trap_disarm_difficulty === 'number' ? values.trap_disarm_difficulty : hasTrap ? 10 : null,
          trap_damage_type: hasTrap && typeof values.trap_damage_type === 'string' ? values.trap_damage_type : hasTrap ? 'physical' : null,
          trap_damage: hasTrap && typeof values.trap_damage === 'number' ? values.trap_damage : hasTrap ? 1 : null,
          bidirectional: typeof values.bidirectional === 'boolean' ? values.bidirectional : true,
          return_exit_name: typeof values.return_exit_name === 'string'
            ? values.return_exit_name
            : values.exit_name,
        };
        const ok = await mutate(
          () => api('/connections', { method: 'POST', body: JSON.stringify(payload) }),
          'Connection created',
        );
        if (!ok) throw new Error('The backend rejected the connection.');
        return payload;
      },
    });
    return () => lifecycle.abort();
  }, [areaId, mutate, nodes.length]);

  const onConnect = useCallback((candidate: Connection) => {
    if (candidate.source && candidate.target && candidate.source !== candidate.target) {
      const existing = graph?.connections.find((item) =>
        (item.source_room_id === candidate.source && item.destination_room_id === candidate.target)
        || (item.source_room_id === candidate.target && item.destination_room_id === candidate.source),
      );
      if (existing) {
        setSelectedEdgeId(edgeId(existing));
        setSelectedRoomId(null);
        setNotice('Those locations are already connected');
        window.setTimeout(() => setNotice(''), 1800);
        return;
      }
      setConnection(candidate);
    } else {
      setError('A location cannot connect to itself.');
    }
  }, [graph]);

  const savePosition = useCallback(async (_: unknown, node: Node) => {
    try {
      await api(`/rooms/${node.id}/position`, {
        method: 'PATCH',
        body: JSON.stringify(node.position),
      });
      const positionedNodes = nodes.map((item) =>
        item.id === node.id ? { ...item, position: node.position } : item,
      );
      const positions = new globalThis.Map(
        positionedNodes.map((item) => [item.id, item.position]),
      );
      setEdges((current) => current.map((edge) => ({
        ...edge,
        ...connectionHandles(positions.get(edge.source), positions.get(edge.target)),
      })));
      setNotice('Layout saved');
      window.setTimeout(() => setNotice(''), 1200);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not save position.');
      await loadGraph(areaId);
    }
  }, [areaId, loadGraph, nodes, setEdges]);

  if (loading) {
    return <main className="center-state">Opening the location editor…</main>;
  }

  return (
    <main className="editor-shell">
      <header className="editor-header">
        <div className="brand-mark">
          {workspaceMode === 'locations' ? <Map size={19} /> : <Swords size={19} />}
        </div>
        <div className="editor-title">
          <p className="kicker">DM workspace</p>
          <h1>{workspaceMode === 'locations' ? 'Location editor' : 'Combat'}</h1>
        </div>
        <nav className="workspace-tabs" aria-label="DM workspace">
          <button
            type="button"
            className={workspaceMode === 'locations' ? 'active' : ''}
            onClick={() => setWorkspaceMode('locations')}
          >
            <Map size={14} /> Locations
          </button>
          <button
            type="button"
            className={workspaceMode === 'combat' ? 'active' : ''}
            onClick={() => setWorkspaceMode('combat')}
          >
            <Swords size={14} /> Combat
          </button>
        </nav>
        <NativeSelect
          aria-label="Current area"
          className="area-select"
          value={areaId}
          onChange={(event) => setAreaId(event.target.value)}
        >
          {areas.map((area) => (
            <NativeSelectOption key={area.id} value={area.id}>
              {area.name} · {area.room_count} locations
            </NativeSelectOption>
          ))}
        </NativeSelect>
        {workspaceMode === 'locations' && (
          <>
            <Button variant="outline" size="sm" onClick={() => setAddAreaOpen(true)}>
              <Plus /> Area
            </Button>
            <Button variant="outline" size="sm" onClick={() => setItemLibraryOpen(true)}>
              <Box /> Item library
            </Button>
            <Button variant="outline" size="sm" onClick={() => setFeatureLibraryOpen(true)}>
              <Sparkles /> Feature library
            </Button>
          </>
        )}
        <Button variant="outline" size="sm" onClick={() => setEnemyLibraryOpen(true)}>
          <Skull /> Enemy library
        </Button>
        <div className="header-status"><span /> {notice || 'Saved'}</div>
        {workspaceMode === 'locations' && (
          <Button className="add-location" onClick={() => setAddRoomOpen(true)} disabled={!areaId}>
            <Plus /> Add location
          </Button>
        )}
        {workspaceMode === 'combat' && combatScene && (
          <Button
            className="add-location"
            onClick={() => setAddCombatLandmarkOpen(true)}
            disabled={combatBusy}
          >
            <Plus /> Add landmark
          </Button>
        )}
      </header>

      {error && <div className="error-banner"><CircleAlert size={15} />{error}<button onClick={() => setError('')}>Dismiss</button></div>}

      {workspaceMode === 'combat' ? (
        <CombatWorkspace
          scene={combatScene}
          rooms={graph?.nodes ?? []}
          enemyTemplates={enemyTemplates}
          preferredRoomId={selectedRoomId}
          busy={combatBusy}
          onStart={startCombat}
          onEnd={endCombat}
          onRefresh={() => loadCombat()}
          onPositionLandmark={(landmarkId, x, y) => updateCombat(
            `/combat/landmarks/${landmarkId}`,
            {
              method: 'PATCH',
              body: JSON.stringify({ x, y }),
            },
            'Landmark position saved',
          )}
          onMoveCombatant={(combatant, landmarkId, relation) => updateCombat(
            `/combat/combatants/${combatant.kind}/${combatant.source_id}`,
            {
              method: 'PATCH',
              body: JSON.stringify({ landmark_id: landmarkId, relation }),
            },
            `${combatant.name} moved`,
          )}
          onAddEnemy={(templateId, landmarkId, quantity) => updateCombat(
            '/combat/enemies',
            {
              method: 'POST',
              body: JSON.stringify({
                template_id: templateId,
                landmark_id: landmarkId,
                quantity,
              }),
            },
            `${quantity} enem${quantity === 1 ? 'y' : 'ies'} added`,
          )}
          onRemoveEnemy={(enemyId) => updateCombat(
            `/combat/combatants/enemy/${enemyId}`,
            { method: 'DELETE' },
            'Enemy removed from combat',
          )}
          onNextTurn={() => updateCombat(
            '/combat/turn/next',
            { method: 'POST' },
            'Turn advanced',
          )}
          onPreviousTurn={() => updateCombat(
            '/combat/turn/previous',
            { method: 'POST' },
            'Turn moved back',
          )}
          onSetInitiative={(combatant, initiativeScore) => updateCombat(
            `/combat/initiative/${combatant.kind}/${combatant.source_id}`,
            {
              method: 'PATCH',
              body: JSON.stringify({ initiative_score: initiativeScore }),
            },
            `${combatant.name}'s initiative updated`,
          )}
          onConnectLandmarks={(sourceId, destinationId, distance, obstacle, blocked) => updateCombat(
            '/combat/routes',
            {
              method: 'PUT',
              body: JSON.stringify({
                source_landmark_id: sourceId,
                destination_landmark_id: destinationId,
                distance,
                obstacle,
                blocked,
              }),
            },
            'Combat connection saved',
          )}
          onDeleteLandmark={(landmarkId) => updateCombat(
            `/combat/landmarks/${landmarkId}`,
            { method: 'DELETE' },
            'Landmark removed',
          )}
          onDeleteConnection={(sourceId, destinationId) => updateCombat(
            '/combat/routes',
            {
              method: 'DELETE',
              body: JSON.stringify({
                source_landmark_id: sourceId,
                destination_landmark_id: destinationId,
              }),
            },
            'Combat connection removed',
          )}
        />
      ) : (
        <section className="editor-body">
        <div className="graph-panel">
          {nodes.length ? (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_, node) => { setSelectedRoomId(node.id); setSelectedEdgeId(null); }}
              onEdgeClick={(_, edge) => { setSelectedEdgeId(edge.id); setSelectedRoomId(null); }}
              onNodeDragStop={savePosition}
              onConnect={onConnect}
              connectionMode={ConnectionMode.Loose}
              fitView
              minZoom={0.35}
              maxZoom={1.8}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#334155" gap={28} size={1} />
              <MiniMap pannable zoomable nodeColor="#d39a4a" maskColor="rgba(8, 15, 26, 0.72)" />
              <Controls showInteractive={false} />
            </ReactFlow>
          ) : (
            <div className="empty-canvas">
              <Map size={28} />
              <h2>{areaId ? 'Start this area' : 'Create your first area'}</h2>
              <p>{areaId ? 'Add a location, then connect it to build the playable route.' : 'Areas keep unrelated location graphs separate.'}</p>
              <Button onClick={() => areaId ? setAddRoomOpen(true) : setAddAreaOpen(true)}><Plus /> {areaId ? 'Add location' : 'Create area'}</Button>
            </div>
          )}
          <div className="canvas-hint">Drag to pan · Scroll to zoom · Drag a handle to connect</div>
        </div>

        <aside className="inspector">
          {selectedRoom ? (
            <RoomInspector
              key={`${selectedRoom.id}:${selectedRoom.name}:${selectedRoom.description}:${selectedRoom.room_image_url || ''}`}
              room={selectedRoom}
              connections={graph?.connections ?? []}
              rooms={graph?.nodes ?? []}
              characters={characters}
              onSave={(name, description) => mutate(
                () => api(`/rooms/${selectedRoom.id}`, { method: 'PATCH', body: JSON.stringify({ name, description }) }),
                'Location saved',
              )}
              onUploadImage={(file) => mutate(
                () => uploadRoomImage(selectedRoom.id, file),
                'Room image saved',
              )}
              onRemoveImage={() => mutate(
                () => api(`/rooms/${selectedRoom.id}/image`, { method: 'DELETE' }),
                'Room image removed',
              )}
              onAddContent={(kind) => {
                if (kind === 'enemy') setEnemyPlacementOpen(true);
                else if (kind === 'container') setContainerPlacementOpen(true);
                else setContentKind(kind);
              }}
              onEditContainer={setEditingContainerId}
              onAddRoomFeature={() => {
                setEditingRoomFeature(null);
                setRoomFeatureOpen(true);
              }}
              onEditRoomFeature={(feature) => {
                setEditingRoomFeature(feature);
                setRoomFeatureOpen(true);
              }}
              onRemoveContent={(kind, id) => mutate(
                () => api(
                  kind === 'item'
                    ? `/rooms/${selectedRoom.id}/items/${id}`
                    : kind === 'container'
                      ? `/containers/${id}`
                      : `/rooms/${selectedRoom.id}/entities/${id}`,
                  { method: 'DELETE' },
                ),
                `${kind === 'item' ? 'Item' : kind === 'container' ? 'Container' : 'Enemy'} removed`,
              )}
              onPlaceCharacter={(characterId) => mutate(
                () => api(`/characters/${characterId}/room`, {
                  method: 'PATCH',
                  body: JSON.stringify({ room_id: selectedRoom.id }),
                }),
                'Character moved',
              )}
              onStartCombat={() => startCombat(selectedRoom.id)}
              onDelete={() => setDeleteOpen(true)}
              onSelectConnection={(item) => { setSelectedEdgeId(edgeId(item)); setSelectedRoomId(null); }}
            />
          ) : selectedConnection ? (
            <ConnectionInspector
              key={`${edgeId(selectedConnection)}:${selectedConnection.connection_type}:${selectedConnection.is_open}:${selectedConnection.has_lock}:${selectedConnection.is_locked}:${selectedConnection.is_broken}:${selectedConnection.unlock_difficulty ?? ''}:${selectedConnection.has_trap}:${selectedConnection.trap_state ?? ''}:${selectedConnection.trap_detection_difficulty ?? ''}:${selectedConnection.trap_disarm_difficulty ?? ''}:${selectedConnection.trap_damage_type ?? ''}:${selectedConnection.trap_damage ?? ''}:${selectedConnection.bidirectional}:${selectedConnection.return_exit_name || ''}`}
              connection={selectedConnection}
              rooms={graph?.nodes ?? []}
              onSave={(connectionType, doorState, lockState, unlockDifficulty, hasTrap, trapState, trapDetectionDifficulty, trapDisarmDifficulty, trapDamageType, trapDamage, bidirectional, returnExitName) => mutate(
                () => api('/connections', {
                  method: 'PATCH',
                  body: JSON.stringify({
                    source_room_id: selectedConnection.source_room_id,
                    exit_name: selectedConnection.exit_name,
                    connection_type: connectionType,
                    is_open: connectionType === 'door' && doorState === 'open',
                    has_lock: connectionType === 'door' && lockState !== 'none',
                    is_locked: connectionType === 'door' && lockState === 'locked',
                    is_broken: connectionType === 'door' && lockState === 'broken',
                    unlock_difficulty: connectionType === 'door' && lockState === 'locked' ? unlockDifficulty : null,
                    has_trap: hasTrap,
                    trap_state: hasTrap ? trapState : null,
                    trap_detection_difficulty: hasTrap ? trapDetectionDifficulty : null,
                    trap_disarm_difficulty: hasTrap ? trapDisarmDifficulty : null,
                    trap_damage_type: hasTrap ? trapDamageType : null,
                    trap_damage: hasTrap ? trapDamage : null,
                    bidirectional,
                    return_exit_name: bidirectional ? returnExitName : null,
                  }),
                }),
                'Connection updated',
              )}
              onRemove={() => void mutate(
                () => api('/connections', { method: 'DELETE', body: JSON.stringify({ source_room_id: selectedConnection.source_room_id, exit_name: selectedConnection.exit_name }) }),
                'Connection removed',
              )}
            />
          ) : (
            <div className="inspector-empty"><p>Select a location or connection to edit it.</p></div>
          )}
        </aside>
      </section>
      )}

      <AreaDialog open={addAreaOpen} onOpenChange={setAddAreaOpen} onCreate={async (name, description) => {
        try {
          const id = identifier(name);
          const created = await api<{ id: string }>('/areas', { method: 'POST', body: JSON.stringify({ id, name, description }) });
          await loadAreas(created.id);
          setAddAreaOpen(false);
          setNotice('Area created');
        } catch (requestError) {
          setError(requestError instanceof Error ? requestError.message : 'Could not create the area.');
        }
      }} />
      <RoomDialog open={addRoomOpen} onOpenChange={setAddRoomOpen} onCreate={async (name, description) => {
        const offset = nodes.length * 36;
        const ok = await mutate(
          () => api(`/areas/${areaId}/rooms`, { method: 'POST', body: JSON.stringify({ id: identifier(name), name, description, x: 180 + offset, y: 140 + offset }) }),
          'Location created',
        );
        if (ok) setAddRoomOpen(false);
      }} />
      <CombatLandmarkDialog
        open={addCombatLandmarkOpen}
        onOpenChange={setAddCombatLandmarkOpen}
        onCreate={(name, description) => updateCombat(
          '/combat/landmarks',
          {
            method: 'POST',
            body: JSON.stringify({ name, description }),
          },
          'Landmark added',
        )}
      />
      <ConnectionDialog key={`${connection?.source || ''}:${connection?.sourceHandle || ''}:${connection?.target || ''}:${connection?.targetHandle || ''}`} connection={connection} onOpenChange={(open) => { if (!open) setConnection(null); }} onCreate={async (exitName, connectionType, doorState, lockState, unlockDifficulty, hasTrap, trapState, trapDetectionDifficulty, trapDisarmDifficulty, trapDamageType, trapDamage, bidirectional, returnExitName) => {
        if (!connection?.source || !connection.target) return;
        const ok = await mutate(
          () => api('/connections', { method: 'POST', body: JSON.stringify({ source_room_id: connection.source, destination_room_id: connection.target, exit_name: exitName, connection_type: connectionType, is_open: connectionType === 'door' && doorState === 'open', has_lock: connectionType === 'door' && lockState !== 'none', is_locked: connectionType === 'door' && lockState === 'locked', is_broken: connectionType === 'door' && lockState === 'broken', unlock_difficulty: connectionType === 'door' && lockState === 'locked' ? unlockDifficulty : null, has_trap: hasTrap, trap_state: hasTrap ? trapState : null, trap_detection_difficulty: hasTrap ? trapDetectionDifficulty : null, trap_disarm_difficulty: hasTrap ? trapDisarmDifficulty : null, trap_damage_type: hasTrap ? trapDamageType : null, trap_damage: hasTrap ? trapDamage : null, bidirectional, return_exit_name: bidirectional ? returnExitName : null }) }),
          'Connection created',
        );
        if (ok) setConnection(null);
      }} />
      <ContentDialog kind={contentKind} catalogItems={catalogItems} onOpenChange={(open) => { if (!open) setContentKind(null); }} onCreate={async (name, quantity) => {
        if (!selectedRoom || !contentKind) return;
        const path = contentKind === 'item' ? 'items' : 'entities';
        const payload = contentKind === 'item'
          ? { item_id: name, quantity }
          : { id: identifier(name), name, kind: contentKind };
        const ok = await mutate(
          () => api(`/rooms/${selectedRoom.id}/${path}`, { method: 'POST', body: JSON.stringify(payload) }),
          `${name} added`,
        );
        if (ok) setContentKind(null);
      }} />
      <EnemyPlacementDialog
        open={enemyPlacementOpen}
        templates={enemyTemplates}
        onOpenChange={setEnemyPlacementOpen}
        onPlace={async (templateId, quantity) => {
          if (!selectedRoom) return false;
          const template = enemyTemplates.find((item) => item.id === templateId);
          const ok = await mutate(async () => {
            for (let index = 0; index < quantity; index += 1) {
              await api(`/rooms/${selectedRoom.id}/enemies`, {
                method: 'POST',
                body: JSON.stringify({ template_id: templateId }),
              });
            }
          }, `${template?.name || 'Enemy'} ×${quantity} added`);
          if (ok) setEnemyPlacementOpen(false);
          return ok;
        }}
      />
      <RoomFeatureDialog
        open={roomFeatureOpen}
        feature={editingRoomFeature}
        templates={roomFeatureTemplates}
        onOpenChange={(open) => {
          setRoomFeatureOpen(open);
          if (!open) setEditingRoomFeature(null);
        }}
        onSave={async (record) => {
          if (!selectedRoom) return false;
          const editing = editingRoomFeature;
          const ok = await mutate(
            () => api(
              editing
                ? `/room-features/${editing.id}`
                : `/rooms/${selectedRoom.id}/features`,
              {
                method: editing ? 'PATCH' : 'POST',
                body: JSON.stringify(
                  editing
                    ? record
                    : {
                      ...record,
                      id: identifier(`${selectedRoom.id} ${record.name}`),
                    },
                ),
              },
            ),
            `${record.name} ${editing ? 'updated' : 'added'}`,
          );
          if (ok) {
            setRoomFeatureOpen(false);
            setEditingRoomFeature(null);
          }
          return ok;
        }}
        onDelete={editingRoomFeature ? async () => {
          const ok = await mutate(
            () => api(`/room-features/${editingRoomFeature.id}`, { method: 'DELETE' }),
            `${editingRoomFeature.name} removed`,
          );
          if (ok) {
            setRoomFeatureOpen(false);
            setEditingRoomFeature(null);
          }
          return ok;
        } : undefined}
      />
      <ContainerPlacementDialog
        open={containerPlacementOpen}
        templates={containerTemplates}
        onOpenChange={setContainerPlacementOpen}
        onPlace={async (templateId) => {
          if (!selectedRoom) return false;
          const template = containerTemplates.find((item) => item.id === templateId);
          const ok = await mutate(
            () => api(`/rooms/${selectedRoom.id}/containers`, {
              method: 'POST',
              body: JSON.stringify({ template_id: templateId }),
            }),
            `${template?.name || 'Container'} added`,
          );
          if (ok) setContainerPlacementOpen(false);
          return ok;
        }}
        onCreateAndPlace={async (draft) => {
          if (!selectedRoom) return false;
          const ok = await mutate(async () => {
            const created = await api<ContainerTemplateData>('/container-templates', {
              method: 'POST',
              body: JSON.stringify({
                id: identifier(draft.name),
                name: draft.name,
                type: draft.type,
                description: draft.description,
                default_has_lock: draft.lockState !== 'none',
                default_is_locked: draft.lockState === 'locked',
                default_is_broken: draft.lockState === 'broken',
                default_unlock_difficulty: draft.lockState === 'locked' ? draft.unlockDifficulty : null,
                default_hidden: draft.hidden,
                default_discovery_difficulty: draft.hidden ? draft.discoveryDifficulty : null,
              }),
            });
            await api(`/rooms/${selectedRoom.id}/containers`, {
              method: 'POST',
              body: JSON.stringify({ template_id: created.id }),
            });
          }, `${draft.name} created and added`);
          if (ok) setContainerPlacementOpen(false);
          return ok;
        }}
      />
      <ContainerEditorDialog
        key={selectedContainer?.id ?? 'container-editor'}
        container={selectedContainer}
        catalogItems={catalogItems}
        onOpenChange={(open) => { if (!open) setEditingContainerId(null); }}
        onSave={async (record) => {
          if (!selectedContainer) return false;
          return mutate(
            () => api(`/containers/${selectedContainer.id}`, {
              method: 'PATCH',
              body: JSON.stringify(record),
            }),
            `${record.name} updated`,
          );
        }}
        onAddItem={async (itemId, quantity) => {
          if (!selectedContainer) return false;
          return mutate(
            () => api(`/containers/${selectedContainer.id}/items`, {
              method: 'POST',
              body: JSON.stringify({ item_id: itemId, quantity }),
            }),
            'Container contents updated',
          );
        }}
        onSetQuantity={async (itemId, quantity) => {
          if (!selectedContainer) return false;
          return mutate(
            () => api(`/containers/${selectedContainer.id}/items/${itemId}`, {
              method: 'PUT',
              body: JSON.stringify({ quantity }),
            }),
            'Container contents updated',
          );
        }}
        onRemoveItem={async (itemId) => {
          if (!selectedContainer) return false;
          return mutate(
            () => api(`/containers/${selectedContainer.id}/items/${itemId}`, {
              method: 'DELETE',
            }),
            'Item removed from container',
          );
        }}
      />
      <ItemLibraryDialog
        open={itemLibraryOpen}
        items={catalogItems}
        onOpenChange={setItemLibraryOpen}
        onSave={async (record, itemId) => {
          const ok = await mutate(
            () => api(itemId ? `/items/${itemId}` : '/items', {
              method: itemId ? 'PUT' : 'POST',
              body: JSON.stringify(itemId ? record : { ...record, id: identifier(record.name) }),
            }),
            `${record.name} ${itemId ? 'updated' : 'created'}`,
          );
          if (ok) setItemLibraryOpen(false);
        }}
      />
      <EnemyLibraryDialog
        open={enemyLibraryOpen}
        templates={enemyTemplates}
        catalogItems={catalogItems}
        onOpenChange={setEnemyLibraryOpen}
        onSave={(editingId, record) => mutate(
          () => api(
            editingId ? `/enemy-templates/${editingId}` : '/enemy-templates',
            {
              method: editingId ? 'PUT' : 'POST',
              body: JSON.stringify(
                editingId ? record : { ...record, id: identifier(record.name) },
              ),
            },
          ),
          `${record.name} ${editingId ? 'updated' : 'created'}`,
        )}
        onDelete={(template) => mutate(
          () => api(`/enemy-templates/${template.id}`, { method: 'DELETE' }),
          `${template.name} removed`,
        )}
      />
      <FeatureLibraryDialog
        open={featureLibraryOpen}
        templates={roomFeatureTemplates}
        onOpenChange={setFeatureLibraryOpen}
        onSave={(editingId, record) => mutate(
          () => api(
            editingId
              ? `/room-feature-templates/${editingId}`
              : '/room-feature-templates',
            {
              method: editingId ? 'PATCH' : 'POST',
              body: JSON.stringify(
                editingId ? record : { ...record, id: identifier(record.name) },
              ),
            },
          ),
          `${record.name} ${editingId ? 'updated' : 'created'}`,
        )}
        onDelete={(template) => mutate(
          () => api(`/room-feature-templates/${template.id}`, { method: 'DELETE' }),
          `${template.name} removed`,
        )}
      />
      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {selectedRoom?.name}?</AlertDialogTitle>
            <AlertDialogDescription>Attached connections will be removed. Occupied locations must be emptied first.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => {
              if (selectedRoom) void mutate(() => api(`/rooms/${selectedRoom.id}`, { method: 'DELETE' }), 'Location deleted');
            }}>Delete location</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}

function RoomInspector({ room, connections, rooms, characters, onSave, onUploadImage, onRemoveImage, onAddContent, onEditContainer, onAddRoomFeature, onEditRoomFeature, onRemoveContent, onPlaceCharacter, onStartCombat, onDelete, onSelectConnection }: {
  room: RoomData;
  connections: ConnectionData[];
  rooms: RoomData[];
  characters: CharacterSummary[];
  onSave: (name: string, description: string) => Promise<boolean>;
  onUploadImage: (file: File) => Promise<boolean>;
  onRemoveImage: () => Promise<boolean>;
  onAddContent: (kind: ContentKind) => void;
  onEditContainer: (id: string) => void;
  onAddRoomFeature: () => void;
  onEditRoomFeature: (feature: {
    id: string;
    room_id: string;
    name: string;
    description: string;
    feature_type: string;
  }) => void;
  onRemoveContent: (kind: ContentKind, id: string) => Promise<boolean>;
  onPlaceCharacter: (characterId: number) => Promise<boolean>;
  onStartCombat: () => Promise<boolean>;
  onDelete: () => void;
  onSelectConnection: (connection: ConnectionData) => void;
}) {
  const [name, setName] = useState(room.name);
  const [description, setDescription] = useState(room.description);
  const [characterId, setCharacterId] = useState('');
  const [imageBusy, setImageBusy] = useState(false);
  const [imageError, setImageError] = useState('');
  const imageInput = useRef<HTMLInputElement>(null);
  const attached = connections.filter((connection) => connection.source_room_id === room.id);
  const roomName = (id: string) => rooms.find((item) => item.id === id)?.name || id;
  const selectedCharacter = characters.find((character) => String(character.id) === characterId);
  const roomFeatures = room.room_features ?? [];
  return (
    <>
      <div className="inspector__topline"><span>Selected location</span><Badge variant="outline">{room.counts.players} players</Badge></div>
      <h2>{room.name}</h2>
      <p className="room-id">{room.id}</p>
      <Button className="start-combat-location" onClick={() => void onStartCombat()}>
        <Swords /> Start combat here
      </Button>
      <div className="inspector__section edit-fields">
        <label htmlFor="room-name">Name</label>
        <Input id="room-name" value={name} onChange={(event) => setName(event.target.value)} />
        <label htmlFor="room-description">Description</label>
        <Textarea id="room-description" value={description} onChange={(event) => setDescription(event.target.value)} />
        <Button size="sm" onClick={() => void onSave(name, description)}><Save /> Save details</Button>
      </div>
      <div className="inspector__section room-image-editor">
        <h3>Room image</h3>
        {room.room_image_url ? (
          <div className="room-image-preview">
            <Image
              src={apiAssetUrl(room.room_image_url)}
              alt={`Visual preview for ${room.name}`}
              fill
              sizes="340px"
              unoptimized
              onLoad={() => setImageError('')}
              onError={() => setImageError('The stored image could not be previewed.')}
            />
          </div>
        ) : (
          <div className="room-image-empty"><ImageIcon size={22} /><span>No visual record uploaded</span></div>
        )}
        <input
          ref={imageInput}
          className="room-image-input"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          disabled={imageBusy}
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
              setImageError('Choose a PNG, JPEG, or WebP image.');
              event.target.value = '';
              return;
            }
            if (file.size > 8 * 1024 * 1024) {
              setImageError('Room images may be at most 8 MB.');
              event.target.value = '';
              return;
            }
            setImageBusy(true);
            setImageError('');
            const saved = await onUploadImage(file);
            if (!saved) setImageError('The room image could not be saved.');
            setImageBusy(false);
            event.target.value = '';
          }}
        />
        <div className="room-image-actions">
          <Button
            type="button"
            size="sm"
            disabled={imageBusy}
            onClick={() => imageInput.current?.click()}
          >
            <Upload /> {imageBusy ? 'Uploading…' : room.room_image_url ? 'Replace image' : 'Upload image'}
          </Button>
          {room.room_image_url && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={imageBusy}
              onClick={async () => {
                setImageBusy(true);
                setImageError('');
                const removed = await onRemoveImage();
                if (!removed) setImageError('The room image could not be removed.');
                setImageBusy(false);
              }}
            >
              <Trash2 /> Remove
            </Button>
          )}
        </div>
        {imageError && <p className="room-image-error">{imageError}</p>}
        <p className="room-image-help">PNG, JPEG, or WebP · maximum 8 MB</p>
      </div>
      <div className="inspector__section">
        <h3>Outgoing connections <span>{attached.length}</span></h3>
        <ul className="connection-list">
          {attached.map((connection) => (
            <li key={edgeId(connection)}>
              <button onClick={() => onSelectConnection(connection)}>{roomName(connection.destination_room_id)}</button>
              <Badge>{connection.exit_name}</Badge>
            </li>
          ))}
          {!attached.length && <li className="muted-row">No outgoing connections</li>}
        </ul>
      </div>
      <div className="inspector__section character-placement">
        <h3>Place character</h3>
        {characters.length ? (
          <>
            <label htmlFor="character-placement">Character</label>
            <NativeSelect
              id="character-placement"
              value={characterId}
              onChange={(event) => setCharacterId(event.target.value)}
            >
              <NativeSelectOption value="">Choose a character…</NativeSelectOption>
              {characters.map((character) => (
                <NativeSelectOption key={character.id} value={character.id}>
                  {character.name}
                  {character.is_active ? ' · active' : ''}
                  {character.current_room_id ? ` · ${roomName(character.current_room_id)}` : ' · unplaced'}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Button
              size="sm"
              disabled={!selectedCharacter || selectedCharacter.current_room_id === room.id}
              onClick={async () => {
                if (selectedCharacter && await onPlaceCharacter(selectedCharacter.id)) {
                  setCharacterId('');
                }
              }}
            >
              <Users />
              {selectedCharacter?.current_room_id === room.id ? 'Already here' : 'Move here'}
            </Button>
          </>
        ) : (
          <p className="muted-row">No selectable characters exist yet.</p>
        )}
      </div>
      <div className="inspector__section content-summary">
        <h3>Room contents</h3>
        {room.players.map((item) => <p key={item.id}><Users size={15} />{item.name}</p>)}
        {room.enemies.map((item) => (
          <p key={item.id}>
            <Skull size={15} />{item.name}
            {item.current_hp !== null && item.max_hp !== null && (
              <strong>{item.current_hp}/{item.max_hp} HP</strong>
            )}
            {item.status !== 'active' && <Badge variant="outline">{item.status}</Badge>}
            <button className="remove-content" type="button" title={`Remove ${item.name}`} aria-label={`Remove ${item.name}`} onClick={() => void onRemoveContent('enemy', item.id)}><Trash2 size={14} /></button>
          </p>
        ))}
        {room.loose_items.map((item) => <p key={item.id}><Sparkles size={15} />{item.name}<strong>×{item.quantity}</strong><button className="remove-content" type="button" title={`Remove ${item.name}`} aria-label={`Remove ${item.name}`} onClick={() => void onRemoveContent('item', item.id)}><Trash2 size={14} /></button></p>)}
        {(room.containers as PlacedContainer[]).map((item) => (
          <p key={item.id}>
            <Button type="button" variant="ghost" size="sm" onClick={() => onEditContainer(item.id)}>
              <Box size={15} />{item.name}
            </Button>
            {item.is_locked && <strong>Locked</strong>}
            {item.is_broken && <strong>Broken lock</strong>}
            {item.hidden && <strong>Hidden · DC {item.discovery_difficulty ?? '?'}</strong>}
            <strong>{item.item_count} items</strong>
            <button className="remove-content" type="button" title={`Remove ${item.name}`} aria-label={`Remove ${item.name}`} onClick={() => void onRemoveContent('container', item.id)}><Trash2 size={14} /></button>
          </p>
        ))}
        <h4>Room Features</h4>
        {roomFeatures.map((feature) => (
          <p key={feature.id}>
            <Button type="button" variant="ghost" size="sm" onClick={() => onEditRoomFeature(feature)}>
              <Sparkles size={15} />{feature.name}
            </Button>
            <Badge variant="outline">{feature.feature_type}</Badge>
          </p>
        ))}
        {!roomFeatures.length && <p className="muted-row">No room features.</p>}
        {!room.players.length && !room.enemies.length && !room.loose_items.length && !room.containers.length && !roomFeatures.length && <p className="muted-row">This location is empty.</p>}
      </div>
      <div className="inspector__actions">
        <Button variant="outline" onClick={() => onAddContent('enemy')}>Add enemy</Button>
        <Button variant="outline" onClick={() => onAddContent('item')}>Add item</Button>
        <Button variant="outline" onClick={() => onAddContent('container')}>Add container</Button>
        <Button variant="outline" onClick={onAddRoomFeature}>Add feature</Button>
      </div>
      <Button className="delete-location" variant="ghost" onClick={onDelete}><Trash2 /> Delete location</Button>
    </>
  );
}

function ConnectionInspector({ connection, rooms, onSave, onRemove }: { connection: ConnectionData; rooms: RoomData[]; onSave: (connectionType: MapConnectionType, doorState: DoorState, lockState: DoorLockState, unlockDifficulty: number, hasTrap: boolean, trapState: TrapState, trapDetectionDifficulty: number, trapDisarmDifficulty: number, trapDamageType: TrapDamageType, trapDamage: number, bidirectional: boolean, returnExitName: string) => Promise<boolean>; onRemove: () => void }) {
  const roomName = (id: string) => rooms.find((room) => room.id === id)?.name || id;
  const [bidirectional, setBidirectional] = useState(connection.bidirectional);
  const [returnExitName, setReturnExitName] = useState(connection.return_exit_name || connection.exit_name);
  const [connectionType, setConnectionType] = useState<MapConnectionType>(connection.connection_type === 'door' ? 'door' : 'hallway');
  const [doorState, setDoorState] = useState<DoorState>(connection.is_open ? 'open' : 'closed');
  const [lockState, setLockState] = useState<DoorLockState>(connection.has_lock ? (connection.is_broken ? 'broken' : connection.is_locked ? 'locked' : 'unlocked') : 'none');
  const [unlockDifficulty, setUnlockDifficulty] = useState(connection.unlock_difficulty ?? 10);
  const [hasTrap, setHasTrap] = useState(connection.has_trap);
  const [trapState, setTrapState] = useState<TrapState>(connection.trap_state ?? 'armed');
  const [trapDetectionDifficulty, setTrapDetectionDifficulty] = useState(connection.trap_detection_difficulty ?? 10);
  const [trapDisarmDifficulty, setTrapDisarmDifficulty] = useState(connection.trap_disarm_difficulty ?? 10);
  const [trapDamageType, setTrapDamageType] = useState<TrapDamageType>(normalizedTrapDamageType(connection.trap_damage_type));
  const [trapDamage, setTrapDamage] = useState(connection.trap_damage ?? 1);
  return (
    <>
      <div className="inspector__topline"><span>Selected connection</span><Badge>{connectionType === 'door' ? 'Door' : 'Hallway'}</Badge></div>
      <h2>{connection.exit_name}</h2>
      <div className="route-card"><strong>{roomName(connection.source_room_id)}</strong><span>{connection.bidirectional ? '↔' : '→'}</span><strong>{roomName(connection.destination_room_id)}</strong></div>
      <label className="dialog-label" htmlFor="connection-type">Map marker</label>
      <NativeSelect id="connection-type" value={connectionType} onChange={(event) => setConnectionType(event.target.value as MapConnectionType)}>
        <NativeSelectOption value="door">Door</NativeSelectOption>
        <NativeSelectOption value="hallway">Hallway</NativeSelectOption>
      </NativeSelect>
      {connectionType === 'door' && <>
        <label className="dialog-label" htmlFor="connection-door-state">Door state</label>
        <NativeSelect id="connection-door-state" value={doorState} onChange={(event) => { const next = event.target.value as DoorState; setDoorState(next); if (next === 'open' && lockState === 'locked') setLockState('unlocked'); }}>
          <NativeSelectOption value="closed">Closed</NativeSelectOption>
          <NativeSelectOption value="open">Open</NativeSelectOption>
        </NativeSelect>
        <label className="dialog-label" htmlFor="connection-lock-state">Lock state</label>
        <NativeSelect id="connection-lock-state" value={lockState} onChange={(event) => { const next = event.target.value as DoorLockState; setLockState(next); if (next === 'locked') setDoorState('closed'); }}>
          <NativeSelectOption value="none">No lock</NativeSelectOption>
          <NativeSelectOption value="unlocked">Unlocked</NativeSelectOption>
          <NativeSelectOption value="locked">Locked</NativeSelectOption>
          <NativeSelectOption value="broken">Broken</NativeSelectOption>
        </NativeSelect>
        {lockState === 'locked' && <><label className="dialog-label" htmlFor="connection-unlock-difficulty">Unlock difficulty (1–30)</label><Input id="connection-unlock-difficulty" type="number" min={1} max={30} step={1} value={unlockDifficulty} onChange={(event) => setUnlockDifficulty(Number(event.target.value))} /></>}
      </>}
      <label className="dialog-label" htmlFor="connection-trap-state">Trap</label>
      <NativeSelect id="connection-trap-state" value={hasTrap ? 'trapped' : 'none'} onChange={(event) => { const trapped = event.target.value === 'trapped'; setHasTrap(trapped); if (trapped) setTrapState('armed'); }}>
        <NativeSelectOption value="none">No trap</NativeSelectOption>
        <NativeSelectOption value="trapped">Trapped</NativeSelectOption>
      </NativeSelect>
      {hasTrap && <>
        <label className="dialog-label" htmlFor="connection-trap-status">Trap state</label>
        <NativeSelect id="connection-trap-status" value={trapState} onChange={(event) => setTrapState(event.target.value as TrapState)}>
          <NativeSelectOption value="armed">Armed</NativeSelectOption>
          <NativeSelectOption value="disarmed">Disarmed</NativeSelectOption>
          <NativeSelectOption value="triggered">Triggered</NativeSelectOption>
        </NativeSelect>
        <label className="dialog-label" htmlFor="connection-trap-difficulty">Insight detection difficulty (1–30)</label>
        <Input id="connection-trap-difficulty" type="number" min={1} max={30} step={1} value={trapDetectionDifficulty} onChange={(event) => setTrapDetectionDifficulty(Number(event.target.value))} />
        <label className="dialog-label" htmlFor="connection-trap-disarm-difficulty">Disarm difficulty (1–30)</label>
        <Input id="connection-trap-disarm-difficulty" type="number" min={1} max={30} step={1} value={trapDisarmDifficulty} onChange={(event) => setTrapDisarmDifficulty(Number(event.target.value))} />
        <label className="dialog-label" htmlFor="connection-trap-damage-type">Damage type</label>
        <NativeSelect id="connection-trap-damage-type" value={trapDamageType} onChange={(event) => setTrapDamageType(event.target.value as TrapDamageType)}>
          {TRAP_DAMAGE_TYPES.map((item) => <NativeSelectOption key={item.value} value={item.value}>{item.label}</NativeSelectOption>)}
        </NativeSelect>
        <label className="dialog-label" htmlFor="connection-trap-damage">Damage</label>
        <Input id="connection-trap-damage" type="number" min={1} step={1} value={trapDamage} onChange={(event) => setTrapDamage(Number(event.target.value))} />
      </>}
      <label className="dialog-label" htmlFor="connection-direction">Direction</label>
      <NativeSelect id="connection-direction" value={bidirectional ? 'two-way' : 'one-way'} onChange={(event) => setBidirectional(event.target.value === 'two-way')}>
        <NativeSelectOption value="two-way">Two-way passage</NativeSelectOption>
        <NativeSelectOption value="one-way">One-way passage</NativeSelectOption>
      </NativeSelect>
      {bidirectional && <><label className="dialog-label" htmlFor="return-exit-name">Return exit name</label><Input id="return-exit-name" value={returnExitName} onChange={(event) => setReturnExitName(event.target.value)} /></>}
      <p className="inspector-note">Movement rules update immediately when this passage is saved.</p>
      <Button disabled={(bidirectional && !returnExitName.trim()) || (connectionType === 'door' && lockState === 'locked' && (!Number.isInteger(unlockDifficulty) || unlockDifficulty < 1 || unlockDifficulty > 30)) || (hasTrap && ((!Number.isInteger(trapDetectionDifficulty) || trapDetectionDifficulty < 1 || trapDetectionDifficulty > 30) || (!Number.isInteger(trapDisarmDifficulty) || trapDisarmDifficulty < 1 || trapDisarmDifficulty > 30) || (!Number.isInteger(trapDamage) || trapDamage < 1)))} onClick={() => void onSave(connectionType, doorState, lockState, unlockDifficulty, hasTrap, trapState, trapDetectionDifficulty, trapDisarmDifficulty, trapDamageType, trapDamage, bidirectional, returnExitName)}><Save /> Save connection</Button>
      <Button variant="destructive" onClick={onRemove}><Trash2 /> Remove connection</Button>
    </>
  );
}

function AreaDialog({ open, onOpenChange, onCreate }: { open: boolean; onOpenChange: (open: boolean) => void; onCreate: (name: string, description: string) => Promise<void> }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  return <EditorDialog open={open} onOpenChange={onOpenChange} title="Create area" description="Start a separate location graph." name={name} setName={setName} details={description} setDetails={setDescription} action="Create area" onSubmit={() => onCreate(name, description)} />;
}

function RoomDialog({ open, onOpenChange, onCreate }: { open: boolean; onOpenChange: (open: boolean) => void; onCreate: (name: string, description: string) => Promise<void> }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  return <EditorDialog open={open} onOpenChange={onOpenChange} title="Add location" description="Coordinates are assigned automatically; drag the node afterward." name={name} setName={setName} details={description} setDetails={setDescription} action="Add location" onSubmit={() => onCreate(name, description)} />;
}

function CombatLandmarkDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (name: string, description: string) => Promise<boolean>;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    if (!open) {
      setName('');
      setDescription('');
    }
  }, [open]);

  return (
    <EditorDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add landmark"
      description="Add a combat-only landmark. It starts unconnected in a free part of the room."
      name={name}
      setName={setName}
      details={description}
      setDetails={setDescription}
      action="Add landmark"
      onSubmit={async () => {
        if (await onCreate(name, description)) {
          onOpenChange(false);
        }
      }}
    />
  );
}

function RoomFeatureDialog({
  open,
  feature,
  templates,
  onOpenChange,
  onSave,
  onDelete,
}: {
  open: boolean;
  feature: {
    id: string;
    room_id: string;
    name: string;
    description: string;
    feature_type: string;
  } | null;
  templates: RoomFeatureTemplateData[];
  onOpenChange: (open: boolean) => void;
  onSave: (record: {
    name: string;
    description: string;
    feature_type: string;
  }) => Promise<boolean>;
  onDelete?: () => Promise<boolean>;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [featureType, setFeatureType] = useState('furniture');
  const [templateId, setTemplateId] = useState('');
  const availableTemplates = [
    ...DEFAULT_ROOM_FEATURE_TEMPLATES.filter(
      (preset) => !templates.some((template) => template.id === preset.id),
    ),
    ...templates,
  ];

  useEffect(() => {
    if (!open) return;
    setTemplateId('');
    setName(feature?.name ?? '');
    setDescription(feature?.description ?? '');
    setFeatureType(feature?.feature_type ?? 'furniture');
  }, [feature, open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{feature ? `Edit ${feature.name}` : 'Add Room Feature'}</DialogTitle>
          <DialogDescription>
            Room Features are persistent descriptive objects in this location.
          </DialogDescription>
        </DialogHeader>
        {!feature && availableTemplates.length > 0 && (
          <>
            <label className="dialog-label" htmlFor="room-feature-template">From feature library</label>
            <NativeSelect
              id="room-feature-template"
              value={templateId}
              onChange={(event) => {
                const nextId = event.target.value;
                setTemplateId(nextId);
                const template = availableTemplates.find((item) => item.id === nextId);
                if (!template) return;
                setName(template.name);
                setDescription(template.description);
                setFeatureType(template.feature_type);
              }}
            >
              <NativeSelectOption value="">Create from scratch…</NativeSelectOption>
              {availableTemplates.map((template) => (
                <NativeSelectOption key={template.id} value={template.id}>{template.name}</NativeSelectOption>
              ))}
            </NativeSelect>
          </>
        )}
        <label className="dialog-label" htmlFor="room-feature-name">Name</label>
        <Input id="room-feature-name" value={name} onChange={(event) => setName(event.target.value)} />
        <label className="dialog-label" htmlFor="room-feature-type">Type</label>
        <NativeSelect id="room-feature-type" value={featureType} onChange={(event) => setFeatureType(event.target.value)}>
          <NativeSelectOption value="furniture">furniture</NativeSelectOption>
          <NativeSelectOption value="decoration">decoration</NativeSelectOption>
          <NativeSelectOption value="structure">structure</NativeSelectOption>
          <NativeSelectOption value="environmental">environmental</NativeSelectOption>
          <NativeSelectOption value="other">other</NativeSelectOption>
        </NativeSelect>
        <label className="dialog-label" htmlFor="room-feature-description">Description</label>
        <Textarea id="room-feature-description" value={description} onChange={(event) => setDescription(event.target.value)} />
        <DialogFooter>
          {feature && onDelete && (
            <Button type="button" variant="outline" onClick={() => void onDelete()}>
              <Trash2 /> Delete
            </Button>
          )}
          <Button
            disabled={!name.trim()}
            onClick={() => void onSave({
              name,
              description,
              feature_type: featureType,
            })}
          >
            <Save /> {feature ? 'Save Room Feature' : 'Add Room Feature'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const DEFAULT_ROOM_FEATURE_TEMPLATES: RoomFeatureTemplateData[] = [
  {
    id: 'wooden_table',
    name: 'Wooden Table',
    feature_type: 'furniture',
    description: 'A sturdy wooden table with a worn, practical surface.',
  },
  {
    id: 'wooden_chair',
    name: 'Wooden Chair',
    feature_type: 'furniture',
    description: 'A plain wooden chair, scuffed from years of use.',
  },
  {
    id: 'simple_bed',
    name: 'Simple Bed',
    feature_type: 'furniture',
    description: 'A simple bed with a wooden frame and a thin mattress.',
  },
  {
    id: 'wooden_bench',
    name: 'Wooden Bench',
    feature_type: 'furniture',
    description: 'A long wooden bench suitable for halls, taverns, and waiting rooms.',
  },
  {
    id: 'bookshelf',
    name: 'Bookshelf',
    feature_type: 'furniture',
    description: 'A tall shelf built to hold books, ledgers, or small curios.',
  },
  {
    id: 'fireplace',
    name: 'Fireplace',
    feature_type: 'structure',
    description: 'A stone fireplace set into the wall.',
  },
  {
    id: 'stone_pillar',
    name: 'Stone Pillar',
    feature_type: 'structure',
    description: 'A heavy stone pillar supporting the structure above.',
  },
  {
    id: 'window',
    name: 'Window',
    feature_type: 'structure',
    description: 'A simple window looking out beyond the room.',
  },
  {
    id: 'wall_torch',
    name: 'Wall Torch',
    feature_type: 'decoration',
    description: 'A wall-mounted torch holder that can provide light when lit.',
  },
  {
    id: 'rug',
    name: 'Rug',
    feature_type: 'decoration',
    description: 'A worn rug spread across part of the floor.',
  },
  {
    id: 'tapestry',
    name: 'Tapestry',
    feature_type: 'decoration',
    description: 'A hanging tapestry used to decorate an otherwise bare wall.',
  },
  {
    id: 'brazier',
    name: 'Brazier',
    feature_type: 'environmental',
    description: 'A metal brazier that can hold a small fire for heat or light.',
  },
];

function isDefaultRoomFeatureTemplate(templateId: string | undefined): boolean {
  return DEFAULT_ROOM_FEATURE_TEMPLATES.some((template) => template.id === templateId);
}

function FeatureLibraryDialog({
  open,
  templates,
  onOpenChange,
  onSave,
  onDelete,
}: {
  open: boolean;
  templates: RoomFeatureTemplateData[];
  onOpenChange: (open: boolean) => void;
  onSave: (
    editingId: string | undefined,
    record: { name: string; description: string; feature_type: string },
  ) => Promise<boolean>;
  onDelete: (template: RoomFeatureTemplateData) => Promise<boolean>;
}) {
  const [editingId, setEditingId] = useState<string | undefined>();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [featureType, setFeatureType] = useState('furniture');
  const availableTemplates = [
    ...DEFAULT_ROOM_FEATURE_TEMPLATES.filter(
      (preset) => !templates.some((template) => template.id === preset.id),
    ),
    ...templates,
  ];
  const isPersistedEdit = (
    editingId !== undefined && !isDefaultRoomFeatureTemplate(editingId)
  );

  const editTemplate = (template?: RoomFeatureTemplateData) => {
    setEditingId(template?.id);
    setName(template?.name ?? '');
    setDescription(template?.description ?? '');
    setFeatureType(template?.feature_type ?? 'furniture');
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Feature library</DialogTitle>
          <DialogDescription>
            Create reusable room features once, then place independent copies in any room.
          </DialogDescription>
        </DialogHeader>
        <div className="catalog-heading">
          <div className="catalog-count">{availableTemplates.length} feature types available</div>
          <button type="button" onClick={() => editTemplate()}>New feature</button>
        </div>
        <div className="catalog-list" aria-label="Existing room feature types">
          {availableTemplates.map((template) => (
            <button
              type="button"
              className={editingId === template.id ? 'selected' : ''}
              key={template.id}
              onClick={() => editTemplate(template)}
            >
              <span>{template.name}</span>
              <Badge variant="outline">{template.feature_type}</Badge>
            </button>
          ))}
        </div>
        <div className="catalog-grid">
          <label className="dialog-label" htmlFor="feature-template-name">
            Name
            <Input id="feature-template-name" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="dialog-label" htmlFor="feature-template-type">
            Type
            <NativeSelect id="feature-template-type" value={featureType} onChange={(event) => setFeatureType(event.target.value)}>
              <NativeSelectOption value="furniture">furniture</NativeSelectOption>
              <NativeSelectOption value="decoration">decoration</NativeSelectOption>
              <NativeSelectOption value="structure">structure</NativeSelectOption>
              <NativeSelectOption value="environmental">environmental</NativeSelectOption>
              <NativeSelectOption value="other">other</NativeSelectOption>
            </NativeSelect>
          </label>
        </div>
        <label className="dialog-label" htmlFor="feature-template-description">Description</label>
        <Textarea id="feature-template-description" value={description} onChange={(event) => setDescription(event.target.value)} />
        <DialogFooter>
          {isPersistedEdit && (
            <Button
              type="button"
              variant="outline"
              onClick={async () => {
                const template = templates.find((item) => item.id === editingId);
                if (template && await onDelete(template)) editTemplate();
              }}
            >
              <Trash2 /> Delete
            </Button>
          )}
          <Button
            disabled={!name.trim()}
            onClick={async () => {
              if (await onSave(isPersistedEdit ? editingId : undefined, { name, description, feature_type: featureType })) {
                editTemplate();
              }
            }}
          >
            <Save /> {isPersistedEdit ? 'Save feature type' : editingId ? 'Create custom copy' : 'Create feature type'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EditorDialog({ open, onOpenChange, title, description, name, setName, details, setDetails, action, onSubmit }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description: string; name: string; setName: (value: string) => void; details: string; setDetails: (value: string) => void; action: string; onSubmit: () => Promise<void> }) {
  const prefix = title.toLowerCase().replaceAll(' ', '-');
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{description}</DialogDescription></DialogHeader>
        <label className="dialog-label" htmlFor={`${prefix}-name`}>Name</label>
        <Input id={`${prefix}-name`} value={name} onChange={(event) => setName(event.target.value)} />
        <label className="dialog-label" htmlFor={`${prefix}-description`}>Description</label>
        <Textarea id={`${prefix}-description`} value={details} onChange={(event) => setDetails(event.target.value)} />
        <DialogFooter><Button disabled={!name.trim()} onClick={() => void onSubmit()}>{action}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ConnectionDialog({ connection, onOpenChange, onCreate }: { connection: Connection | null; onOpenChange: (open: boolean) => void; onCreate: (name: string, connectionType: MapConnectionType, doorState: DoorState, lockState: DoorLockState, unlockDifficulty: number, hasTrap: boolean, trapState: TrapState, trapDetectionDifficulty: number, trapDisarmDifficulty: number, trapDamageType: TrapDamageType, trapDamage: number, bidirectional: boolean, returnName: string) => Promise<void> }) {
  const [name, setName] = useState(() => exitNameForHandle(connection?.sourceHandle));
  const [bidirectional, setBidirectional] = useState(true);
  const [connectionType, setConnectionType] = useState<MapConnectionType>('hallway');
  const [doorState, setDoorState] = useState<DoorState>('closed');
  const [lockState, setLockState] = useState<DoorLockState>('none');
  const [unlockDifficulty, setUnlockDifficulty] = useState(10);
  const [hasTrap, setHasTrap] = useState(false);
  const [trapState, setTrapState] = useState<TrapState>('armed');
  const [trapDetectionDifficulty, setTrapDetectionDifficulty] = useState(10);
  const [trapDisarmDifficulty, setTrapDisarmDifficulty] = useState(10);
  const [trapDamageType, setTrapDamageType] = useState<TrapDamageType>('physical');
  const [trapDamage, setTrapDamage] = useState(1);
  const [returnName, setReturnName] = useState(() => exitNameForHandle(connection?.targetHandle));
  return (
    <Dialog open={Boolean(connection)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Create passage</DialogTitle><DialogDescription>Passages work in both directions by default. Choose one-way only when the return path should be blocked.</DialogDescription></DialogHeader>
        <label className="dialog-label" htmlFor="connection-name">Exit name</label>
        <Input id="connection-name" value={name} onChange={(event) => { const next = event.target.value; setReturnName((current) => current === name ? next : current); setName(next); }} />
        <label className="dialog-label" htmlFor="new-connection-type">Map marker</label>
        <NativeSelect id="new-connection-type" value={connectionType} onChange={(event) => setConnectionType(event.target.value as MapConnectionType)}>
          <NativeSelectOption value="door">Door</NativeSelectOption>
          <NativeSelectOption value="hallway">Hallway</NativeSelectOption>
        </NativeSelect>
        {connectionType === 'door' && <>
          <label className="dialog-label" htmlFor="new-connection-door-state">Door state</label>
          <NativeSelect id="new-connection-door-state" value={doorState} onChange={(event) => { const next = event.target.value as DoorState; setDoorState(next); if (next === 'open' && lockState === 'locked') setLockState('unlocked'); }}>
            <NativeSelectOption value="closed">Closed</NativeSelectOption>
            <NativeSelectOption value="open">Open</NativeSelectOption>
          </NativeSelect>
          <label className="dialog-label" htmlFor="new-connection-lock-state">Lock state</label>
          <NativeSelect id="new-connection-lock-state" value={lockState} onChange={(event) => { const next = event.target.value as DoorLockState; setLockState(next); if (next === 'locked') setDoorState('closed'); }}>
            <NativeSelectOption value="none">No lock</NativeSelectOption>
            <NativeSelectOption value="unlocked">Unlocked</NativeSelectOption>
            <NativeSelectOption value="locked">Locked</NativeSelectOption>
            <NativeSelectOption value="broken">Broken</NativeSelectOption>
          </NativeSelect>
          {lockState === 'locked' && <><label className="dialog-label" htmlFor="new-connection-unlock-difficulty">Unlock difficulty (1–30)</label><Input id="new-connection-unlock-difficulty" type="number" min={1} max={30} step={1} value={unlockDifficulty} onChange={(event) => setUnlockDifficulty(Number(event.target.value))} /></>}
        </>}
        <label className="dialog-label" htmlFor="new-connection-trap-state">Trap</label>
        <NativeSelect id="new-connection-trap-state" value={hasTrap ? 'trapped' : 'none'} onChange={(event) => { const trapped = event.target.value === 'trapped'; setHasTrap(trapped); if (trapped) setTrapState('armed'); }}>
          <NativeSelectOption value="none">No trap</NativeSelectOption>
          <NativeSelectOption value="trapped">Trapped</NativeSelectOption>
        </NativeSelect>
        {hasTrap && <>
          <label className="dialog-label" htmlFor="new-connection-trap-status">Trap state</label>
          <NativeSelect id="new-connection-trap-status" value={trapState} onChange={(event) => setTrapState(event.target.value as TrapState)}>
            <NativeSelectOption value="armed">Armed</NativeSelectOption>
            <NativeSelectOption value="disarmed">Disarmed</NativeSelectOption>
            <NativeSelectOption value="triggered">Triggered</NativeSelectOption>
          </NativeSelect>
          <label className="dialog-label" htmlFor="new-connection-trap-difficulty">Insight detection difficulty (1–30)</label>
          <Input id="new-connection-trap-difficulty" type="number" min={1} max={30} step={1} value={trapDetectionDifficulty} onChange={(event) => setTrapDetectionDifficulty(Number(event.target.value))} />
          <label className="dialog-label" htmlFor="new-connection-trap-disarm-difficulty">Disarm difficulty (1–30)</label>
          <Input id="new-connection-trap-disarm-difficulty" type="number" min={1} max={30} step={1} value={trapDisarmDifficulty} onChange={(event) => setTrapDisarmDifficulty(Number(event.target.value))} />
          <label className="dialog-label" htmlFor="new-connection-trap-damage-type">Damage type</label>
          <NativeSelect id="new-connection-trap-damage-type" value={trapDamageType} onChange={(event) => setTrapDamageType(event.target.value as TrapDamageType)}>
            {TRAP_DAMAGE_TYPES.map((item) => <NativeSelectOption key={item.value} value={item.value}>{item.label}</NativeSelectOption>)}
          </NativeSelect>
          <label className="dialog-label" htmlFor="new-connection-trap-damage">Damage</label>
          <Input id="new-connection-trap-damage" type="number" min={1} step={1} value={trapDamage} onChange={(event) => setTrapDamage(Number(event.target.value))} />
        </>}
        <label className="dialog-label" htmlFor="new-connection-direction">Direction</label>
        <NativeSelect id="new-connection-direction" value={bidirectional ? 'two-way' : 'one-way'} onChange={(event) => setBidirectional(event.target.value === 'two-way')}>
          <NativeSelectOption value="two-way">Two-way passage</NativeSelectOption>
          <NativeSelectOption value="one-way">One-way passage</NativeSelectOption>
        </NativeSelect>
        {bidirectional && <><label className="dialog-label" htmlFor="new-return-exit-name">Return exit name</label><Input id="new-return-exit-name" value={returnName} onChange={(event) => setReturnName(event.target.value)} /></>}
        <DialogFooter><Button disabled={!name.trim() || (bidirectional && !returnName.trim()) || (connectionType === 'door' && lockState === 'locked' && (!Number.isInteger(unlockDifficulty) || unlockDifficulty < 1 || unlockDifficulty > 30)) || (hasTrap && ((!Number.isInteger(trapDetectionDifficulty) || trapDetectionDifficulty < 1 || trapDetectionDifficulty > 30) || (!Number.isInteger(trapDisarmDifficulty) || trapDisarmDifficulty < 1 || trapDisarmDifficulty > 30) || (!Number.isInteger(trapDamage) || trapDamage < 1)))} onClick={() => void onCreate(name, connectionType, doorState, lockState, unlockDifficulty, hasTrap, trapState, trapDetectionDifficulty, trapDisarmDifficulty, trapDamageType, trapDamage, bidirectional, returnName)}>Create connection</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ContainerPlacementDialog({
  open,
  templates,
  onOpenChange,
  onPlace,
  onCreateAndPlace,
}: {
  open: boolean;
  templates: ContainerTemplateData[];
  onOpenChange: (open: boolean) => void;
  onPlace: (templateId: string) => Promise<boolean>;
  onCreateAndPlace: (draft: ContainerTemplateDraft) => Promise<boolean>;
}) {
  const [templateId, setTemplateId] = useState('');
  const [search, setSearch] = useState('');
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [containerType, setContainerType] = useState<ContainerTypeValue>('wooden_chest');
  const [description, setDescription] = useState('');
  const [lockState, setLockState] = useState<DoorLockState>('none');
  const [unlockDifficulty, setUnlockDifficulty] = useState(10);
  const [hidden, setHidden] = useState(false);
  const [discoveryDifficulty, setDiscoveryDifficulty] = useState(10);
  const filtered = templates.filter((template) => {
    const query = search.trim().toLocaleLowerCase();
    return !query
      || template.name.toLocaleLowerCase().includes(query)
      || template.type.toLocaleLowerCase().includes(query);
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add container</DialogTitle>
          <DialogDescription>
            Place a reusable container definition, or create a new definition and place it here.
          </DialogDescription>
        </DialogHeader>
        {!creating ? (
          <>
            <label className="dialog-label" htmlFor="container-search">Search library</label>
            <Input id="container-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Chest, corpse, shelf…" />
            <label className="dialog-label" htmlFor="container-template">Container</label>
            <NativeSelect id="container-template" value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
              <NativeSelectOption value="">Choose a container…</NativeSelectOption>
              {filtered.map((template) => (
                <NativeSelectOption key={template.id} value={template.id}>
                  {template.name} · {CONTAINER_TYPES.find((item) => item.value === template.type)?.label ?? template.type}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Button type="button" variant="outline" onClick={() => setCreating(true)}>
              <Plus /> New container definition
            </Button>
            <DialogFooter>
              <Button
                disabled={!templateId}
                onClick={async () => {
                  if (await onPlace(templateId)) onOpenChange(false);
                }}
              >
                Add container
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <label className="dialog-label" htmlFor="new-container-name">Name</label>
            <Input id="new-container-name" value={name} onChange={(event) => setName(event.target.value)} />
            <label className="dialog-label" htmlFor="new-container-type">Type</label>
            <NativeSelect id="new-container-type" value={containerType} onChange={(event) => setContainerType(event.target.value as ContainerTypeValue)}>
              {CONTAINER_TYPES.map((item) => <NativeSelectOption key={item.value} value={item.value}>{item.label}</NativeSelectOption>)}
            </NativeSelect>
            <label className="dialog-label" htmlFor="new-container-description">Description</label>
            <Textarea id="new-container-description" value={description} onChange={(event) => setDescription(event.target.value)} />
            <label className="dialog-label" htmlFor="new-container-lock">Default lock</label>
            <NativeSelect id="new-container-lock" value={lockState} onChange={(event) => setLockState(event.target.value as DoorLockState)}>
              <NativeSelectOption value="none">No lock</NativeSelectOption>
              <NativeSelectOption value="unlocked">Unlocked</NativeSelectOption>
              <NativeSelectOption value="locked">Locked</NativeSelectOption>
              <NativeSelectOption value="broken">Broken</NativeSelectOption>
            </NativeSelect>
            {lockState === 'locked' && (
              <>
                <label className="dialog-label" htmlFor="new-container-unlock-difficulty">Unlock difficulty (1–30)</label>
                <Input id="new-container-unlock-difficulty" type="number" min={1} max={30} value={unlockDifficulty} onChange={(event) => setUnlockDifficulty(Number(event.target.value))} />
              </>
            )}
            <label className="dialog-label" htmlFor="new-container-hidden">Default visibility</label>
            <NativeSelect id="new-container-hidden" value={hidden ? 'hidden' : 'visible'} onChange={(event) => setHidden(event.target.value === 'hidden')}>
              <NativeSelectOption value="visible">Visible</NativeSelectOption>
              <NativeSelectOption value="hidden">Hidden</NativeSelectOption>
            </NativeSelect>
            {hidden && (
              <>
                <label className="dialog-label" htmlFor="new-container-discovery-difficulty">Discovery DC (1–30)</label>
                <Input id="new-container-discovery-difficulty" type="number" min={1} max={30} value={discoveryDifficulty} onChange={(event) => setDiscoveryDifficulty(Number(event.target.value))} />
              </>
            )}
            <Button type="button" variant="outline" onClick={() => setCreating(false)}>Back to library</Button>
            <DialogFooter>
              <Button
                disabled={
                  !name.trim()
                  || (lockState === 'locked' && (!Number.isInteger(unlockDifficulty) || unlockDifficulty < 1 || unlockDifficulty > 30))
                  || (hidden && (!Number.isInteger(discoveryDifficulty) || discoveryDifficulty < 1 || discoveryDifficulty > 30))
                }
                onClick={async () => {
                  if (await onCreateAndPlace({
                    name,
                    type: containerType,
                    description,
                    lockState,
                    unlockDifficulty,
                    hidden,
                    discoveryDifficulty,
                  })) onOpenChange(false);
                }}
              >
                Create and place
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ContainerEditorDialog({
  container,
  catalogItems,
  onOpenChange,
  onSave,
  onAddItem,
  onSetQuantity,
  onRemoveItem,
}: {
  container: PlacedContainer | null;
  catalogItems: CatalogItem[];
  onOpenChange: (open: boolean) => void;
  onSave: (record: {
    name: string;
    description: string;
    has_lock: boolean;
    is_locked: boolean;
    is_broken: boolean;
    unlock_difficulty: number | null;
    hidden: boolean;
    discovery_difficulty: number | null;
    is_open: boolean;
    searched: boolean;
  }) => Promise<boolean>;
  onAddItem: (itemId: string, quantity: number) => Promise<boolean>;
  onSetQuantity: (itemId: string, quantity: number) => Promise<boolean>;
  onRemoveItem: (itemId: string) => Promise<boolean>;
}) {
  const [name, setName] = useState(container?.name ?? '');
  const [description, setDescription] = useState(container?.description ?? '');
  const [lockState, setLockState] = useState<DoorLockState>(
    container?.has_lock
      ? container.is_broken
        ? 'broken'
        : container.is_locked
          ? 'locked'
          : 'unlocked'
      : 'none',
  );
  const [unlockDifficulty, setUnlockDifficulty] = useState(container?.unlock_difficulty ?? 10);
  const [hidden, setHidden] = useState(container?.hidden ?? false);
  const [discoveryDifficulty, setDiscoveryDifficulty] = useState(container?.discovery_difficulty ?? 10);
  const [isOpen, setIsOpen] = useState(container?.is_open ?? false);
  const [searched, setSearched] = useState(container?.searched ?? false);
  const [itemId, setItemId] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [quantities, setQuantities] = useState<Record<string, number>>({});

  return (
    <Dialog open={Boolean(container)} onOpenChange={onOpenChange}>
      <DialogContent>
        {container && (
          <>
            <DialogHeader>
              <DialogTitle>Edit {container.name}</DialogTitle>
              <DialogDescription>
                {CONTAINER_TYPES.find((item) => item.value === container.type)?.label ?? container.type}
                {' · '}
                template {container.template_id}
              </DialogDescription>
            </DialogHeader>
            <label className="dialog-label" htmlFor="container-editor-name">Name</label>
            <Input id="container-editor-name" value={name} onChange={(event) => setName(event.target.value)} />
            <label className="dialog-label" htmlFor="container-editor-description">Description</label>
            <Textarea id="container-editor-description" value={description} onChange={(event) => setDescription(event.target.value)} />

            <h3>Contents</h3>
            {container.contents.map((item) => (
              <div key={item.id}>
                <strong>{item.name}</strong>
                <Input
                  aria-label={`${item.name} quantity`}
                  type="number"
                  min={1}
                  value={quantities[item.id] ?? item.quantity}
                  onChange={(event) => setQuantities((current) => ({
                    ...current,
                    [item.id]: Number(event.target.value),
                  }))}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={(quantities[item.id] ?? item.quantity) < 1}
                  onClick={() => void onSetQuantity(item.id, quantities[item.id] ?? item.quantity)}
                >
                  Save quantity
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => void onRemoveItem(item.id)}>
                  <Trash2 /> Remove
                </Button>
              </div>
            ))}
            {!container.contents.length && <p className="muted-row">Container is empty.</p>}
            <label className="dialog-label" htmlFor="container-editor-item">Add item</label>
            <NativeSelect id="container-editor-item" value={itemId} onChange={(event) => setItemId(event.target.value)}>
              <NativeSelectOption value="">Choose an item…</NativeSelectOption>
              {catalogItems.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.name} · {item.item_type}</NativeSelectOption>)}
            </NativeSelect>
            <label className="dialog-label" htmlFor="container-editor-item-quantity">Quantity</label>
            <Input id="container-editor-item-quantity" type="number" min={1} value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!itemId || quantity < 1}
              onClick={async () => {
                if (await onAddItem(itemId, quantity)) {
                  setItemId('');
                  setQuantity(1);
                }
              }}
            >
              <Plus /> Add item
            </Button>

            <h3>Lock</h3>
            <NativeSelect
              value={lockState}
              onChange={(event) => {
                const next = event.target.value as DoorLockState;
                setLockState(next);
                if (next === 'locked') setIsOpen(false);
              }}
            >
              <NativeSelectOption value="none">No lock</NativeSelectOption>
              <NativeSelectOption value="unlocked">Unlocked</NativeSelectOption>
              <NativeSelectOption value="locked">Locked</NativeSelectOption>
              <NativeSelectOption value="broken">Broken</NativeSelectOption>
            </NativeSelect>
            {lockState === 'locked' && (
              <Input type="number" min={1} max={30} value={unlockDifficulty} onChange={(event) => setUnlockDifficulty(Number(event.target.value))} />
            )}

            <h3>Hidden / discovery</h3>
            <NativeSelect value={hidden ? 'hidden' : 'visible'} onChange={(event) => setHidden(event.target.value === 'hidden')}>
              <NativeSelectOption value="visible">Visible</NativeSelectOption>
              <NativeSelectOption value="hidden">Hidden</NativeSelectOption>
            </NativeSelect>
            {hidden && (
              <Input type="number" min={1} max={30} value={discoveryDifficulty} onChange={(event) => setDiscoveryDifficulty(Number(event.target.value))} />
            )}
            <label>
              <input type="checkbox" checked={isOpen} disabled={lockState === 'locked'} onChange={(event) => setIsOpen(event.target.checked)} />
              Opened
            </label>
            <label>
              <input type="checkbox" checked={searched} onChange={(event) => setSearched(event.target.checked)} />
              Searched
            </label>

            <DialogFooter>
              <Button
                disabled={
                  !name.trim()
                  || (lockState === 'locked' && (!Number.isInteger(unlockDifficulty) || unlockDifficulty < 1 || unlockDifficulty > 30))
                  || (hidden && (!Number.isInteger(discoveryDifficulty) || discoveryDifficulty < 1 || discoveryDifficulty > 30))
                }
                onClick={async () => {
                  const saved = await onSave({
                    name,
                    description,
                    has_lock: lockState !== 'none',
                    is_locked: lockState === 'locked',
                    is_broken: lockState === 'broken',
                    unlock_difficulty: lockState === 'locked' ? unlockDifficulty : null,
                    hidden,
                    discovery_difficulty: hidden ? discoveryDifficulty : null,
                    is_open: isOpen && lockState !== 'locked',
                    searched,
                  });
                  if (saved) onOpenChange(false);
                }}
              >
                <Save /> Save container
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ContentDialog({ kind, catalogItems, onOpenChange, onCreate }: { kind: ContentKind | null; catalogItems: CatalogItem[]; onOpenChange: (open: boolean) => void; onCreate: (name: string, quantity: number) => Promise<void> }) {
  const [name, setName] = useState('');
  const [quantity, setQuantity] = useState(1);
  return (
    <Dialog open={Boolean(kind)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Add {kind}</DialogTitle><DialogDescription>{kind === 'item' ? 'Choose an existing item from the shared library.' : 'This creates a persisted world object in the selected location.'}</DialogDescription></DialogHeader>
        <label className="dialog-label" htmlFor="content-name">{kind === 'item' ? 'Item' : 'Name'}</label>
        {kind === 'item' ? (
          <NativeSelect id="content-name" value={name} onChange={(event) => setName(event.target.value)}>
            <NativeSelectOption value="">Choose an item…</NativeSelectOption>
            {catalogItems.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.name} · {item.item_type}</NativeSelectOption>)}
          </NativeSelect>
        ) : <Input id="content-name" value={name} onChange={(event) => setName(event.target.value)} />}
        {kind === 'item' && <><label className="dialog-label" htmlFor="content-quantity">Quantity</label><Input id="content-quantity" type="number" min={1} value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} /></>}
        <DialogFooter><Button disabled={!name.trim() || quantity < 1} onClick={() => void onCreate(name, quantity)}>Add {kind}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function emptyEnemyTemplateDraft(): EnemyTemplateDraft {
  return {
    name: '',
    description: '',
    race: 'Unknown',
    difficulty_level: 1,
    strength: 0,
    dexterity: 0,
    arcana: 0,
    vitality: 0,
    insight: 0,
    personality: 0,
    max_hp: 7,
    armor: 0,
    magical_resistance: 0,
    attack_dc: 12,
    defense_dc: 12,
    damage: '1d4',
    attack_profile: 'Basic attack',
    special_ability: null,
    typical_behaviour: 'Unknown',
    main_hand_item_id: null,
    off_hand_item_id: null,
    armor_item_id: null,
  };
}

function EnemyPlacementDialog({
  open,
  templates,
  onOpenChange,
  onPlace,
}: {
  open: boolean;
  templates: EnemyTemplateData[];
  onOpenChange: (open: boolean) => void;
  onPlace: (templateId: string, quantity: number) => Promise<boolean>;
}) {
  const [templateId, setTemplateId] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [search, setSearch] = useState('');
  const filtered = templates.filter((template) => {
    const query = search.trim().toLocaleLowerCase();
    return !query
      || template.name.toLocaleLowerCase().includes(query)
      || template.race.toLocaleLowerCase().includes(query);
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add enemy</DialogTitle>
          <DialogDescription>
            Place independent enemy instances from the shared enemy library.
          </DialogDescription>
        </DialogHeader>

        <label className="dialog-label" htmlFor="enemy-search">
          Search library
        </label>
        <Input
          id="enemy-search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Skeleton, bandit, troll…"
        />

        <label className="dialog-label" htmlFor="enemy-template">
          Enemy type
        </label>
        <NativeSelect
          id="enemy-template"
          value={templateId}
          onChange={(event) => setTemplateId(event.target.value)}
        >
          <NativeSelectOption value="">
            Choose an enemy…
          </NativeSelectOption>
          {filtered.map((template) => (
            <NativeSelectOption
              key={template.id}
              value={template.id}
            >
              {template.name} · {template.race} · {template.max_hp} HP
            </NativeSelectOption>
          ))}
        </NativeSelect>

        <label className="dialog-label" htmlFor="enemy-quantity">
          Quantity
        </label>
        <Input
          id="enemy-quantity"
          type="number"
          min={1}
          max={20}
          value={quantity}
          onChange={(event) => setQuantity(Number(event.target.value))}
        />

        <DialogFooter>
          <Button
            disabled={
              !templateId
              || !Number.isInteger(quantity)
              || quantity < 1
              || quantity > 20
            }
            onClick={async () => {
              if (await onPlace(templateId, quantity)) {
                setTemplateId('');
                setQuantity(1);
                setSearch('');
              }
            }}
          >
            Add {quantity > 1 ? `${quantity} enemies` : 'enemy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EnemyLibraryDialog({
  open,
  templates,
  catalogItems,
  onOpenChange,
  onSave,
  onDelete,
}: {
  open: boolean;
  templates: EnemyTemplateData[];
  catalogItems: CatalogItem[];
  onOpenChange: (open: boolean) => void;
  onSave: (
    editingId: string | undefined,
    record: EnemyTemplateDraft,
  ) => Promise<boolean>;
  onDelete: (template: EnemyTemplateData) => Promise<boolean>;
}) {
  const [editingId, setEditingId] = useState<string | undefined>();
  const [draft, setDraft] = useState<EnemyTemplateDraft>(
    () => emptyEnemyTemplateDraft(),
  );
  const editingTemplate = templates.find(
    (template) => template.id === editingId,
  );
  const weapons = catalogItems.filter(
    (item) => item.item_type === 'weapon',
  );
  const armorItems = catalogItems.filter(
    (item) => item.item_type === 'armor',
  );
  const [search, setSearch] = useState('');
  const [raceFilter, setRaceFilter] = useState('all');
  const races = Array.from(
    new Set(templates.map((template) => template.race).filter(Boolean)),
  ).sort((left, right) => left.localeCompare(right));
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredTemplates = templates.filter((template) => (
    (raceFilter === 'all' || template.race === raceFilter)
    && (
      !normalizedSearch
      || template.name.toLocaleLowerCase().includes(normalizedSearch)
      || template.race.toLocaleLowerCase().includes(normalizedSearch)
      || template.typical_behaviour.toLocaleLowerCase().includes(normalizedSearch)
    )
  ));

  function update<K extends keyof EnemyTemplateDraft>(
    key: K,
    value: EnemyTemplateDraft[K],
  ) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function editTemplate(template?: EnemyTemplateData) {
    setEditingId(template?.id);
    setDraft(template ? {
      name: template.name,
      description: template.description,
      race: template.race,
      difficulty_level: template.difficulty_level,
      strength: template.strength,
      dexterity: template.dexterity,
      arcana: template.arcana,
      vitality: template.vitality,
      insight: template.insight,
      personality: template.personality,
      max_hp: template.max_hp,
      armor: template.armor,
      magical_resistance: template.magical_resistance,
      attack_dc: template.attack_dc,
      defense_dc: template.defense_dc,
      damage: template.damage,
      attack_profile: template.attack_profile,
      special_ability: template.special_ability,
      typical_behaviour: template.typical_behaviour,
      main_hand_item_id: template.main_hand_item_id,
      off_hand_item_id: template.off_hand_item_id,
      armor_item_id: template.armor_item_id,
    } : emptyEnemyTemplateDraft());
  }

  const invalidNumber = [
    draft.difficulty_level,
    draft.strength,
    draft.dexterity,
    draft.arcana,
    draft.vitality,
    draft.insight,
    draft.personality,
    draft.armor,
    draft.magical_resistance,
  ].some(
    (value) => !Number.isInteger(value) || value < 0,
  );

  const invalidPositive = [
    draft.max_hp,
    draft.attack_dc,
    draft.defense_dc,
  ].some(
    (value) => !Number.isInteger(value) || value < 1,
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="enemy-library-dialog sm:max-w-[860px]">
        <DialogHeader>
          <DialogTitle>Enemy library</DialogTitle>
          <DialogDescription>
            Define reusable enemy types here. Click an existing type to edit or delete it. Placed copies keep independent HP and world state.
          </DialogDescription>
        </DialogHeader>

        <div className="catalog-heading">
          <div className="catalog-count">
            {filteredTemplates.length} of {templates.length} enemy types
          </div>
          <button
            type="button"
            onClick={() => editTemplate()}
          >
            New enemy
          </button>
        </div>

        <div className="catalog-grid enemy-library-filters">
          <label className="dialog-label" htmlFor="enemy-library-search">
            Search
            <Input
              id="enemy-library-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name, race or behaviour…"
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-library-race">
            Race
            <NativeSelect
              id="enemy-library-race"
              value={raceFilter}
              onChange={(event) => setRaceFilter(event.target.value)}
            >
              <NativeSelectOption value="all">All races</NativeSelectOption>
              {races.map((race) => (
                <NativeSelectOption key={race} value={race}>
                  {race}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
        </div>

        <div
          className="catalog-list"
          aria-label="Existing enemy types"
        >
          {filteredTemplates.map((template) => (
            <button
              type="button"
              className={
                editingId === template.id
                  ? 'selected'
                  : ''
              }
              key={template.id}
              onClick={() => editTemplate(template)}
            >
              <span>{template.name}</span>
              <Badge variant="outline">
                {template.race} · {template.max_hp} HP
              </Badge>
            </button>
          ))}
        </div>

        <div className="catalog-grid">
          <label className="dialog-label" htmlFor="enemy-template-name">
            Name
            <Input
              id="enemy-template-name"
              value={draft.name}
              onChange={(event) => update('name', event.target.value)}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-race">
            Race
            <Input
              id="enemy-template-race"
              value={draft.race}
              onChange={(event) => update('race', event.target.value)}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-difficulty">
            Difficulty
            <Input
              id="enemy-template-difficulty"
              type="number"
              min={0}
              value={draft.difficulty_level}
              onChange={(event) => update('difficulty_level', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-hp">
            Max HP
            <Input
              id="enemy-template-hp"
              type="number"
              min={1}
              value={draft.max_hp}
              onChange={(event) => update('max_hp', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-strength">
            Strength
            <Input
              id="enemy-template-strength"
              type="number"
              min={0}
              value={draft.strength}
              onChange={(event) => update('strength', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-dexterity">
            Dexterity
            <Input
              id="enemy-template-dexterity"
              type="number"
              min={0}
              value={draft.dexterity}
              onChange={(event) => update('dexterity', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-arcana">
            Arcana
            <Input
              id="enemy-template-arcana"
              type="number"
              min={0}
              value={draft.arcana}
              onChange={(event) => update('arcana', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-vitality">
            Vitality
            <Input
              id="enemy-template-vitality"
              type="number"
              min={0}
              value={draft.vitality}
              onChange={(event) => update('vitality', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-insight">
            Insight
            <Input
              id="enemy-template-insight"
              type="number"
              min={0}
              value={draft.insight}
              onChange={(event) => update('insight', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-personality">
            Personality
            <Input
              id="enemy-template-personality"
              type="number"
              min={0}
              value={draft.personality}
              onChange={(event) => update('personality', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-armor">
            Armor
            <Input
              id="enemy-template-armor"
              type="number"
              min={0}
              value={draft.armor}
              onChange={(event) => update('armor', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-magic-resistance">
            Magic resistance
            <Input
              id="enemy-template-magic-resistance"
              type="number"
              min={0}
              value={draft.magical_resistance}
              onChange={(event) => update('magical_resistance', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-attack-dc">
            Attack DC
            <Input
              id="enemy-template-attack-dc"
              type="number"
              min={1}
              value={draft.attack_dc}
              onChange={(event) => update('attack_dc', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-defense-dc">
            Defense DC
            <Input
              id="enemy-template-defense-dc"
              type="number"
              min={1}
              value={draft.defense_dc}
              onChange={(event) => update('defense_dc', Number(event.target.value))}
            />
          </label>
        </div>

        <label className="dialog-label" htmlFor="enemy-template-description">
          Description
        </label>
        <Textarea
          id="enemy-template-description"
          value={draft.description}
          onChange={(event) => update('description', event.target.value)}
        />

        <label className="dialog-label" htmlFor="enemy-template-damage">
          Damage
        </label>
        <Input
          id="enemy-template-damage"
          value={draft.damage}
          onChange={(event) => update('damage', event.target.value)}
          placeholder="1d6"
        />

        <label className="dialog-label" htmlFor="enemy-template-attack-profile">
          Attack profile
        </label>
        <Input
          id="enemy-template-attack-profile"
          value={draft.attack_profile}
          onChange={(event) => update('attack_profile', event.target.value)}
        />

        <label className="dialog-label" htmlFor="enemy-template-behaviour">
          Typical behaviour
        </label>
        <Textarea
          id="enemy-template-behaviour"
          value={draft.typical_behaviour}
          onChange={(event) => update('typical_behaviour', event.target.value)}
        />

        <label className="dialog-label" htmlFor="enemy-template-ability">
          Special ability
        </label>
        <Textarea
          id="enemy-template-ability"
          value={draft.special_ability ?? ''}
          onChange={(event) => update(
            'special_ability',
            event.target.value.trim()
              ? event.target.value
              : null,
          )}
        />

        <div className="catalog-grid">
          <label className="dialog-label" htmlFor="enemy-template-main-hand">
            Main hand
            <NativeSelect
              id="enemy-template-main-hand"
              value={draft.main_hand_item_id ?? ''}
              onChange={(event) => update(
                'main_hand_item_id',
                event.target.value || null,
              )}
            >
              <NativeSelectOption value="">None</NativeSelectOption>
              {weapons.map((item) => (
                <NativeSelectOption key={item.id} value={item.id}>
                  {item.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>

          <label className="dialog-label" htmlFor="enemy-template-off-hand">
            Off hand
            <NativeSelect
              id="enemy-template-off-hand"
              value={draft.off_hand_item_id ?? ''}
              onChange={(event) => update(
                'off_hand_item_id',
                event.target.value || null,
              )}
            >
              <NativeSelectOption value="">None</NativeSelectOption>
              {weapons.map((item) => (
                <NativeSelectOption key={item.id} value={item.id}>
                  {item.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>

          <label className="dialog-label" htmlFor="enemy-template-armor-item">
            Armor
            <NativeSelect
              id="enemy-template-armor-item"
              value={draft.armor_item_id ?? ''}
              onChange={(event) => update(
                'armor_item_id',
                event.target.value || null,
              )}
            >
              <NativeSelectOption value="">None</NativeSelectOption>
              {armorItems.map((item) => (
                <NativeSelectOption key={item.id} value={item.id}>
                  {item.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
        </div>

        <DialogFooter className="enemy-library-footer">
          {editingTemplate && (
            <Button
              variant="destructive"
              onClick={async () => {
                if (await onDelete(editingTemplate)) {
                  editTemplate();
                }
              }}
            >
              <Trash2 /> Delete
            </Button>
          )}

          <Button
            disabled={
              !draft.name.trim()
              || !draft.race.trim()
              || !draft.damage.trim()
              || !draft.attack_profile.trim()
              || !draft.typical_behaviour.trim()
              || invalidNumber
              || invalidPositive
            }
            onClick={async () => {
              if (await onSave(editingId, draft)) {
                editTemplate();
              }
            }}
          >
            <Save />
            {editingId
              ? 'Save enemy type'
              : 'Create enemy type'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type ItemDraft = {
  name: string;
  item_type: CatalogItem['item_type'];
  description: string;
  rarity: string;
  value: number;
  weight: number;
  slot_cost: number;
  grip?: string;
  durability?: number;
  damage?: number;
  damage_type?: string;
  protection?: number;
  dodge_penalty?: number;
  strength_requirement?: number;
  capacity?: number;
  can_equip?: boolean;
  affected_amount?: number;
  content?: string;
};

function ItemLibraryDialog({ open, items, onOpenChange, onSave }: { open: boolean; items: CatalogItem[]; onOpenChange: (open: boolean) => void; onSave: (record: ItemDraft, itemId?: string) => Promise<void> }) {
  const [editingId, setEditingId] = useState<string | undefined>();
  const [name, setName] = useState('');
  const [itemType, setItemType] = useState<CatalogItem['item_type']>('misc');
  const [description, setDescription] = useState('');
  const [rarity, setRarity] = useState('Common');
  const [value, setValue] = useState(0);
  const [weight, setWeight] = useState(0);
  const [slotCost, setSlotCost] = useState(1);
  const [power, setPower] = useState(1);
  const [damageType, setDamageType] = useState('physical');
  const [grip, setGrip] = useState('one_handed');
  const [canEquip, setCanEquip] = useState(false);
  const [readableContent, setReadableContent] = useState('');
  const [stackable, setStackable] = useState(false);
  const [itemTypeFilter, setItemTypeFilter] = useState<CatalogItem['item_type'] | 'all'>('all');

  const editingItem = items.find((item) => item.id === editingId);
  const filteredItems = itemTypeFilter === 'all' ? items : items.filter((item) => item.item_type === itemTypeFilter);
  useEffect(() => {
    setStackable(editingItem?.stackable ?? false);
  }, [editingItem]);

  const record: ItemDraft = { name, item_type: itemType, description, rarity, value, weight, slot_cost: slotCost };
  Object.assign(record, { stackable });
  if (itemType === 'weapon') Object.assign(record, { grip, durability: editingItem?.durability ?? 40, damage: power, damage_type: damageType });
  if (itemType === 'armor') Object.assign(record, { protection: power, dodge_penalty: editingItem?.dodge_penalty ?? 0, strength_requirement: editingItem?.strength_requirement ?? 0 });
  if (itemType === 'container') Object.assign(record, { capacity: power, can_equip: canEquip });
  if (itemType === 'consumable') Object.assign(record, { affected_amount: power });
  if (itemType === 'readable') Object.assign(record, { content: readableContent });

  const editItem = (item?: CatalogItem) => {
    setEditingId(item?.id);
    setName(item?.name ?? '');
    setItemType(item?.item_type ?? 'misc');
    setDescription(item?.description ?? '');
    setRarity(item?.rarity ?? 'Common');
    setValue(item?.value ?? 0);
    setWeight(item?.weight ?? 0);
    setSlotCost(item?.slot_cost ?? (item?.item_type === 'readable' && item.weight === 0 ? 0 : 1));
    setReadableContent(item?.content ?? '');
    setGrip(item?.grip ?? 'one_handed');
    setDamageType(item?.damage_type ?? 'physical');
    setCanEquip(item?.can_equip ?? false);
    setPower(
      item?.damage
      ?? item?.protection
      ?? item?.capacity
      ?? item?.affected_amount
      ?? 1
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Item library</DialogTitle><DialogDescription>Create and edit item types here. Rooms and containers can only use entries from this shared library.</DialogDescription></DialogHeader>
        <div className="catalog-heading"><div className="catalog-count">{items.length} item types available</div><button type="button" onClick={() => editItem()}>New item</button></div>
        <label className="dialog-label" htmlFor="item-library-type-filter">Filter by type
          <NativeSelect id="item-library-type-filter" value={itemTypeFilter} onChange={(event) => setItemTypeFilter(event.target.value as CatalogItem['item_type'] | 'all')}>
            <NativeSelectOption value="all">All types</NativeSelectOption>
            <NativeSelectOption value="misc">Misc</NativeSelectOption>
            <NativeSelectOption value="tool">Tool</NativeSelectOption>
            <NativeSelectOption value="weapon">Weapon</NativeSelectOption>
            <NativeSelectOption value="armor">Armor</NativeSelectOption>
            <NativeSelectOption value="clothing">Clothing</NativeSelectOption>
            <NativeSelectOption value="container">Container</NativeSelectOption>
            <NativeSelectOption value="consumable">Consumable</NativeSelectOption>
            <NativeSelectOption value="readable">Readable</NativeSelectOption>
          </NativeSelect>
        </label>
        <div className="catalog-list" aria-label="Existing item types">
          {filteredItems.map((item) => (
            <button type="button" className={editingId === item.id ? 'selected' : ''} key={item.id} onClick={() => editItem(item)}><span>{item.name}</span><Badge variant="outline">{item.item_type}</Badge></button>
          ))}
        </div>
        <div className="catalog-grid">
          <label className="dialog-label" htmlFor="item-name">Name<Input id="item-name" value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label className="dialog-label" htmlFor="item-type">Type<NativeSelect id="item-type" value={itemType} disabled={Boolean(editingId)} onChange={(event) => { const nextType = event.target.value as CatalogItem['item_type']; setItemType(nextType); setStackable(nextType === 'consumable' || nextType === 'tool'); if (nextType === 'readable' && weight === 0) setSlotCost(0); }}><NativeSelectOption value="misc">Misc</NativeSelectOption><NativeSelectOption value="tool">Tool</NativeSelectOption><NativeSelectOption value="weapon">Weapon</NativeSelectOption><NativeSelectOption value="armor">Armor</NativeSelectOption><NativeSelectOption value="clothing">Clothing</NativeSelectOption><NativeSelectOption value="container">Container</NativeSelectOption><NativeSelectOption value="consumable">Consumable</NativeSelectOption><NativeSelectOption value="readable">Readable</NativeSelectOption></NativeSelect></label>
          <label className="dialog-label" htmlFor="item-stackable">Stackable<input id="item-stackable" type="checkbox" checked={stackable} onChange={(event) => setStackable(event.target.checked)} /></label>
          <label className="dialog-label" htmlFor="item-rarity">Rarity<Input id="item-rarity" value={rarity} onChange={(event) => setRarity(event.target.value)} /></label>
          <label className="dialog-label" htmlFor="item-value">Value<Input id="item-value" type="number" min={0} value={value} onChange={(event) => setValue(Number(event.target.value))} /></label>
          <label className="dialog-label" htmlFor="item-weight">Weight<Input id="item-weight" type="number" min={0} value={weight} onChange={(event) => setWeight(Number(event.target.value))} /></label>
          <label className="dialog-label" htmlFor="item-slots">Storage slots<Input id="item-slots" type="number" min={0} value={slotCost} onChange={(event) => setSlotCost(Number(event.target.value))} /></label>
          {!['misc', 'tool', 'clothing', 'readable'].includes(itemType) && <label className="dialog-label" htmlFor="item-power">{itemType === 'weapon' ? 'Damage' : itemType === 'armor' ? 'Protection' : itemType === 'container' ? 'Capacity' : 'Healing'}<Input id="item-power" type="number" min={1} value={power} onChange={(event) => setPower(Number(event.target.value))} /></label>}
          {itemType === 'weapon' && <><label className="dialog-label" htmlFor="item-damage-type">Damage type<Input id="item-damage-type" value={damageType} onChange={(event) => setDamageType(event.target.value)} /></label><label className="dialog-label" htmlFor="item-grip">Grip<NativeSelect id="item-grip" value={grip} onChange={(event) => setGrip(event.target.value)}><NativeSelectOption value="one_handed">One handed</NativeSelectOption><NativeSelectOption value="two_handed">Two handed</NativeSelectOption></NativeSelect></label></>}
          {itemType === 'container' && <label className="catalog-check"><input type="checkbox" checked={canEquip} onChange={(event) => setCanEquip(event.target.checked)} /> Can be equipped</label>}
        </div>
        <label className="dialog-label" htmlFor="item-description">Description</label>
        <Textarea id="item-description" value={description} onChange={(event) => setDescription(event.target.value)} />
        {itemType === 'readable' && <label className="dialog-label" htmlFor="item-readable-content">Readable content<Textarea className="readable-content-input" id="item-readable-content" value={readableContent} onChange={(event) => setReadableContent(event.target.value)} /></label>}
        <DialogFooter><Button disabled={!name.trim() || !rarity.trim() || value < 0 || weight < 0 || slotCost < 0 || power < 1} onClick={() => void onSave(record, editingId)}>{editingId ? 'Save item type' : 'Create item type'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
