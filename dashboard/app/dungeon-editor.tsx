'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Background,
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
  Map,
  Plus,
  Save,
  Skull,
  Sparkles,
  Trash2,
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
import {
  api,
  identifier,
  type AreaGraphData,
  type AreaSummary,
  type CharacterSummary,
  type ConnectionData,
  type RoomData,
} from './api';

type RoomNodeData = RoomData & Record<string, unknown>;
type ContentKind = 'enemy' | 'item' | 'container';

function RoomNode({ data, selected }: NodeProps<Node<RoomNodeData>>) {
  return (
    <article className={`room-node ${selected ? 'room-node--selected' : ''}`}>
      <Handle type="target" position={Position.Top} />
      <div className="room-node__eyebrow">Location</div>
      <h3>{data.name}</h3>
      <div className="room-node__stats" aria-label="Room contents">
        <span title="Players"><Users size={13} />{data.counts.players}</span>
        <span title="Enemies"><Skull size={13} />{data.counts.enemies}</span>
        <span title="Loose items"><Sparkles size={13} />{data.counts.items}</span>
        <span title="Containers"><Box size={13} />{data.counts.containers}</span>
      </div>
      <Handle type="source" position={Position.Bottom} />
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
  return `${connection.source_room_id}::${connection.exit_name}`;
}

function graphEdges(graph: AreaGraphData): Edge[] {
  return graph.connections.map((connection) => ({
    id: edgeId(connection),
    source: connection.source_room_id,
    target: connection.destination_room_id,
    label: connection.exit_name,
    markerEnd: { type: MarkerType.ArrowClosed },
  }));
}

export function DungeonEditor() {
  const [areas, setAreas] = useState<AreaSummary[]>([]);
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
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
  const [addAreaOpen, setAddAreaOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [contentKind, setContentKind] = useState<ContentKind | null>(null);

  const selectedRoom = useMemo(
    () => graph?.nodes.find((room) => room.id === selectedRoomId) ?? null,
    [graph, selectedRoomId],
  );
  const selectedConnection = useMemo(
    () => graph?.connections.find((item) => edgeId(item) === selectedEdgeId) ?? null,
    [graph, selectedEdgeId],
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

  useEffect(() => {
    queueMicrotask(() => {
      void loadAreas();
      void loadCharacters();
    });
  }, [loadAreas, loadCharacters]);
  useEffect(() => {
    if (areaId) queueMicrotask(() => void loadGraph(areaId));
  }, [areaId, loadGraph]);

  const mutate = useCallback(async (action: () => Promise<unknown>, message: string) => {
    try {
      await action();
      await Promise.all([loadGraph(areaId), loadAreas(areaId), loadCharacters()]);
      setNotice(message);
      setError('');
      window.setTimeout(() => setNotice(''), 1800);
      return true;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The change was rejected.');
      return false;
    }
  }, [areaId, loadAreas, loadCharacters, loadGraph]);

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
      description: 'Create a directional gameplay exit between two rooms in the selected area.',
      inputSchema: {
        type: 'object',
        properties: {
          source_room_id: { type: 'string', minLength: 1 },
          destination_room_id: { type: 'string', minLength: 1 },
          exit_name: { type: 'string', minLength: 1 },
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
        const ok = await mutate(
          () => api('/connections', { method: 'POST', body: JSON.stringify(values) }),
          'Connection created',
        );
        if (!ok) throw new Error('The backend rejected the connection.');
        return values;
      },
    });
    return () => lifecycle.abort();
  }, [areaId, mutate, nodes.length]);

  const onConnect = useCallback((candidate: Connection) => {
    if (candidate.source && candidate.target && candidate.source !== candidate.target) {
      setConnection(candidate);
    } else {
      setError('A location cannot connect to itself.');
    }
  }, []);

  const savePosition = useCallback(async (_: unknown, node: Node) => {
    try {
      await api(`/rooms/${node.id}/position`, {
        method: 'PATCH',
        body: JSON.stringify(node.position),
      });
      setNotice('Layout saved');
      window.setTimeout(() => setNotice(''), 1200);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not save position.');
      await loadGraph(areaId);
    }
  }, [areaId, loadGraph]);

  if (loading) {
    return <main className="center-state">Opening the location editor…</main>;
  }

  return (
    <main className="editor-shell">
      <header className="editor-header">
        <div className="brand-mark"><Map size={19} /></div>
        <div className="editor-title">
          <p className="kicker">DM workspace</p>
          <h1>Location editor</h1>
        </div>
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
        <Button variant="outline" size="sm" onClick={() => setAddAreaOpen(true)}>
          <Plus /> Area
        </Button>
        <div className="header-status"><span /> {notice || 'Saved'}</div>
        <Button className="add-location" onClick={() => setAddRoomOpen(true)} disabled={!areaId}>
          <Plus /> Add location
        </Button>
      </header>

      {error && <div className="error-banner"><CircleAlert size={15} />{error}<button onClick={() => setError('')}>Dismiss</button></div>}

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
              key={`${selectedRoom.id}:${selectedRoom.name}:${selectedRoom.description}`}
              room={selectedRoom}
              connections={graph?.connections ?? []}
              rooms={graph?.nodes ?? []}
              characters={characters}
              onSave={(name, description) => mutate(
                () => api(`/rooms/${selectedRoom.id}`, { method: 'PATCH', body: JSON.stringify({ name, description }) }),
                'Location saved',
              )}
              onAddContent={setContentKind}
              onPlaceCharacter={(characterId) => mutate(
                () => api(`/characters/${characterId}/room`, {
                  method: 'PATCH',
                  body: JSON.stringify({ room_id: selectedRoom.id }),
                }),
                'Character moved',
              )}
              onDelete={() => setDeleteOpen(true)}
              onSelectConnection={(item) => { setSelectedEdgeId(edgeId(item)); setSelectedRoomId(null); }}
            />
          ) : selectedConnection ? (
            <ConnectionInspector
              connection={selectedConnection}
              rooms={graph?.nodes ?? []}
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
      <ConnectionDialog connection={connection} onOpenChange={(open) => { if (!open) setConnection(null); }} onCreate={async (exitName) => {
        if (!connection?.source || !connection.target) return;
        const ok = await mutate(
          () => api('/connections', { method: 'POST', body: JSON.stringify({ source_room_id: connection.source, destination_room_id: connection.target, exit_name: exitName }) }),
          'Connection created',
        );
        if (ok) setConnection(null);
      }} />
      <ContentDialog kind={contentKind} onOpenChange={(open) => { if (!open) setContentKind(null); }} onCreate={async (name, quantity) => {
        if (!selectedRoom || !contentKind) return;
        const path = contentKind === 'item' ? 'items' : 'entities';
        const payload = contentKind === 'item'
          ? { id: identifier(name), name, quantity }
          : { id: identifier(name), name, kind: contentKind };
        const ok = await mutate(
          () => api(`/rooms/${selectedRoom.id}/${path}`, { method: 'POST', body: JSON.stringify(payload) }),
          `${name} added`,
        );
        if (ok) setContentKind(null);
      }} />
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

function RoomInspector({ room, connections, rooms, characters, onSave, onAddContent, onPlaceCharacter, onDelete, onSelectConnection }: {
  room: RoomData;
  connections: ConnectionData[];
  rooms: RoomData[];
  characters: CharacterSummary[];
  onSave: (name: string, description: string) => Promise<boolean>;
  onAddContent: (kind: ContentKind) => void;
  onPlaceCharacter: (characterId: number) => Promise<boolean>;
  onDelete: () => void;
  onSelectConnection: (connection: ConnectionData) => void;
}) {
  const [name, setName] = useState(room.name);
  const [description, setDescription] = useState(room.description);
  const [characterId, setCharacterId] = useState('');
  const attached = connections.filter((connection) => connection.source_room_id === room.id);
  const roomName = (id: string) => rooms.find((item) => item.id === id)?.name || id;
  const selectedCharacter = characters.find((character) => String(character.id) === characterId);
  return (
    <>
      <div className="inspector__topline"><span>Selected location</span><Badge variant="outline">{room.counts.players} players</Badge></div>
      <h2>{room.name}</h2>
      <p className="room-id">{room.id}</p>
      <div className="inspector__section edit-fields">
        <label htmlFor="room-name">Name</label>
        <Input id="room-name" value={name} onChange={(event) => setName(event.target.value)} />
        <label htmlFor="room-description">Description</label>
        <Textarea id="room-description" value={description} onChange={(event) => setDescription(event.target.value)} />
        <Button size="sm" onClick={() => void onSave(name, description)}><Save /> Save details</Button>
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
        {room.enemies.map((item) => <p key={item.id}><Skull size={15} />{item.name}</p>)}
        {room.loose_items.map((item) => <p key={item.id}><Sparkles size={15} />{item.name}<strong>×{item.quantity}</strong></p>)}
        {room.containers.map((item) => <p key={item.id}><Box size={15} />{item.name}</p>)}
        {!room.players.length && !room.enemies.length && !room.loose_items.length && !room.containers.length && <p className="muted-row">This location is empty.</p>}
      </div>
      <div className="inspector__actions">
        <Button variant="outline" onClick={() => onAddContent('enemy')}>Add enemy</Button>
        <Button variant="outline" onClick={() => onAddContent('item')}>Add item</Button>
        <Button variant="outline" onClick={() => onAddContent('container')}>Add container</Button>
      </div>
      <Button className="delete-location" variant="ghost" onClick={onDelete}><Trash2 /> Delete location</Button>
    </>
  );
}

function ConnectionInspector({ connection, rooms, onRemove }: { connection: ConnectionData; rooms: RoomData[]; onRemove: () => void }) {
  const roomName = (id: string) => rooms.find((room) => room.id === id)?.name || id;
  return (
    <>
      <div className="inspector__topline"><span>Selected connection</span><Badge>One-way</Badge></div>
      <h2>{connection.exit_name}</h2>
      <div className="route-card"><strong>{roomName(connection.source_room_id)}</strong><span>→</span><strong>{roomName(connection.destination_room_id)}</strong></div>
      <p className="inspector-note">This arrow is a gameplay exit. Removing it immediately changes movement rules.</p>
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

function ConnectionDialog({ connection, onOpenChange, onCreate }: { connection: Connection | null; onOpenChange: (open: boolean) => void; onCreate: (name: string) => Promise<void> }) {
  const [name, setName] = useState('passage');
  return (
    <Dialog open={Boolean(connection)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Name this exit</DialogTitle><DialogDescription>The arrow remains directional and is saved as a real gameplay connection.</DialogDescription></DialogHeader>
        <label className="dialog-label" htmlFor="connection-name">Exit name</label>
        <Input id="connection-name" value={name} onChange={(event) => setName(event.target.value)} />
        <DialogFooter><Button disabled={!name.trim()} onClick={() => void onCreate(name)}>Create connection</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ContentDialog({ kind, onOpenChange, onCreate }: { kind: ContentKind | null; onOpenChange: (open: boolean) => void; onCreate: (name: string, quantity: number) => Promise<void> }) {
  const [name, setName] = useState('');
  const [quantity, setQuantity] = useState(1);
  return (
    <Dialog open={Boolean(kind)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Add {kind}</DialogTitle><DialogDescription>This creates a persisted world object in the selected location.</DialogDescription></DialogHeader>
        <label className="dialog-label" htmlFor="content-name">Name</label>
        <Input id="content-name" value={name} onChange={(event) => setName(event.target.value)} />
        {kind === 'item' && <><label className="dialog-label" htmlFor="content-quantity">Quantity</label><Input id="content-quantity" type="number" min={1} value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} /></>}
        <DialogFooter><Button disabled={!name.trim() || quantity < 1} onClick={() => void onCreate(name, quantity)}>Add {kind}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
