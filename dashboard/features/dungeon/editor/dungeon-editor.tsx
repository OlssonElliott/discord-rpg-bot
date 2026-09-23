'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from '@xyflow/react';
import { CircleAlert } from 'lucide-react';
import { CharacterWorkspace } from '@/features/characters/workspace';
import {
  api,
  identifier,
  type AreaGraphData,
  type AreaSummary,
  type CatalogItem,
  type CharacterSummary,
  type CombatSceneData,
  type CombatStateData,
  type EnemyTemplateData,
} from '@/lib/api';

import {
  connectionHandles,
  edgeId,
  graphEdges,
  graphNodes,
  type RoomNodeData,
} from '@/features/dungeon/editor/graph';
import { DungeonCanvas } from '@/features/dungeon/editor/canvas';
import { CombatWorkspaceController } from '@/features/combat/controller';
import { DungeonInspector } from '@/features/dungeon/inspectors/dungeon';
import { EditorHeader } from '@/features/dungeon/editor/header';
import { DungeonCreationDialogs } from '@/features/dungeon/dialogs/creation';
import { DungeonContentDialogs } from '@/features/dungeon/dialogs/content';
import { DungeonLibraryDialogs } from '@/features/dungeon/dialogs/library';
import type {
  ContainerTemplateData,
  ContentKind,
  PlacedContainer,
  RoomFeatureTemplateData,
} from '@/features/dungeon/types';

export function DungeonEditor() {
  const [workspaceMode, setWorkspaceMode] = useState<'locations' | 'characters' | 'combat'>('locations');
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
  const [inspectorOpen, setInspectorOpen] = useState(true);
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
      <EditorHeader
        workspaceMode={workspaceMode}
        areas={areas}
        areaId={areaId}
        notice={notice}
        hasCombatScene={Boolean(combatScene)}
        combatBusy={combatBusy}
        onWorkspaceModeChange={setWorkspaceMode}
        onAreaChange={setAreaId}
        onAddArea={() => setAddAreaOpen(true)}
        onOpenItemLibrary={() => setItemLibraryOpen(true)}
        onOpenFeatureLibrary={() => setFeatureLibraryOpen(true)}
        onOpenEnemyLibrary={() => setEnemyLibraryOpen(true)}
        onAddRoom={() => setAddRoomOpen(true)}
        onAddCombatLandmark={() => setAddCombatLandmarkOpen(true)}
      />

      {error && <div className="error-banner"><CircleAlert size={15} />{error}<button onClick={() => setError('')}>Dismiss</button></div>}

      {workspaceMode === 'combat' ? (
        <CombatWorkspaceController
          scene={combatScene}
          rooms={graph?.nodes ?? []}
          enemyTemplates={enemyTemplates}
          preferredRoomId={selectedRoomId}
          busy={combatBusy}
          onStart={startCombat}
          onEnd={endCombat}
          onRefresh={loadCombat}
          updateCombat={updateCombat}
        />
      ) : workspaceMode === 'characters' ? (
        <CharacterWorkspace
          characters={characters}
          catalogItems={catalogItems}
          areas={areas}
          onCharactersChanged={loadCharacters}
          onNotice={(message) => {
            setNotice(message);
            window.setTimeout(() => setNotice(''), 1400);
          }}
          onError={setError}
        />
      ) : (
        <section
          className={[
            'editor-body',
            inspectorOpen ? '' : 'editor-body--inspector-closed',
          ].filter(Boolean).join(' ')}
        >
        <DungeonCanvas
          nodes={nodes}
          edges={edges}
          areaId={areaId}
          inspectorOpen={inspectorOpen}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeSelect={(nodeId) => {
            setSelectedRoomId(nodeId);
            setSelectedEdgeId(null);
            setInspectorOpen(true);
          }}
          onEdgeSelect={(edgeId) => {
            setSelectedEdgeId(edgeId);
            setSelectedRoomId(null);
            setInspectorOpen(true);
          }}
          onNodeDragStop={savePosition}
          onConnect={onConnect}
          onCreateRoom={() => setAddRoomOpen(true)}
          onCreateArea={() => setAddAreaOpen(true)}
          onOpenInspector={() => setInspectorOpen(true)}
        />

        <DungeonInspector
          open={inspectorOpen}
          room={selectedRoom}
          connection={selectedConnection}
          rooms={graph?.nodes ?? []}
          connections={graph?.connections ?? []}
          characters={characters}
          mutate={mutate}
          onClose={() => setInspectorOpen(false)}
          onAddContent={(kind) => {
            if (kind === 'enemy') setEnemyPlacementOpen(true);
            else if (kind === 'container') setContainerPlacementOpen(true);
            else setContentKind(kind);
          }}
          onEditContainer={(id) => setEditingContainerId(id)}
          onAddRoomFeature={() => {
            setEditingRoomFeature(null);
            setRoomFeatureOpen(true);
          }}
          onEditRoomFeature={(feature) => {
            setEditingRoomFeature(feature);
            setRoomFeatureOpen(true);
          }}
          onStartCombat={startCombat}
          onDeleteRoom={() => setDeleteOpen(true)}
          onSelectConnection={(item) => {
            setSelectedEdgeId(edgeId(item));
            setSelectedRoomId(null);
          }}
        />
      </section>
      )}

      <DungeonCreationDialogs
        addAreaOpen={addAreaOpen}
        addRoomOpen={addRoomOpen}
        addCombatLandmarkOpen={addCombatLandmarkOpen}
        connection={connection}
        areaId={areaId}
        roomCount={nodes.length}
        onAddAreaOpenChange={setAddAreaOpen}
        onAddRoomOpenChange={setAddRoomOpen}
        onAddCombatLandmarkOpenChange={setAddCombatLandmarkOpen}
        onConnectionChange={setConnection}
        loadAreas={loadAreas}
        mutate={mutate}
        updateCombat={updateCombat}
        onNotice={setNotice}
        onError={setError}
      />
      <DungeonContentDialogs
        contentKind={contentKind}
        catalogItems={catalogItems}
        room={selectedRoom}
        enemyPlacementOpen={enemyPlacementOpen}
        enemyTemplates={enemyTemplates}
        roomFeatureOpen={roomFeatureOpen}
        editingRoomFeature={editingRoomFeature}
        roomFeatureTemplates={roomFeatureTemplates}
        containerPlacementOpen={containerPlacementOpen}
        containerTemplates={containerTemplates}
        selectedContainer={selectedContainer}
        onContentKindChange={setContentKind}
        onEnemyPlacementOpenChange={setEnemyPlacementOpen}
        onRoomFeatureOpenChange={setRoomFeatureOpen}
        onEditingRoomFeatureChange={setEditingRoomFeature}
        onContainerPlacementOpenChange={setContainerPlacementOpen}
        onEditingContainerIdChange={setEditingContainerId}
        mutate={mutate}
      />
      <DungeonLibraryDialogs
        itemLibraryOpen={itemLibraryOpen}
        enemyLibraryOpen={enemyLibraryOpen}
        featureLibraryOpen={featureLibraryOpen}
        deleteOpen={deleteOpen}
        catalogItems={catalogItems}
        enemyTemplates={enemyTemplates}
        roomFeatureTemplates={roomFeatureTemplates}
        selectedRoom={selectedRoom}
        onItemLibraryOpenChange={setItemLibraryOpen}
        onEnemyLibraryOpenChange={setEnemyLibraryOpen}
        onFeatureLibraryOpenChange={setFeatureLibraryOpen}
        onDeleteOpenChange={setDeleteOpen}
        mutate={mutate}
      />
    </main>
  );
}


