'use client';

import {
  Handle,
  MarkerType,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import { Box, Skull, Sparkles, Users } from 'lucide-react';
import type { AreaGraphData, ConnectionData, RoomData } from '@/lib/api';

export type RoomNodeData = RoomData & Record<string, unknown>;

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

export const nodeTypes = { room: RoomNode };

export function graphNodes(graph: AreaGraphData): Node<RoomNodeData>[] {
  return graph.nodes.map((room) => ({
    id: room.id,
    type: 'room',
    position: room.position,
    data: room,
  }));
}

export function edgeId(connection: ConnectionData): string {
  return connection.connection_id || `${connection.source_room_id}::${connection.exit_name}`;
}

type CardinalHandle = 'top' | 'right' | 'bottom' | 'left';

const EXIT_NAME_BY_HANDLE: Record<CardinalHandle, string> = {
  top: 'north',
  right: 'east',
  bottom: 'south',
  left: 'west',
};

export function exitNameForHandle(handle: string | null | undefined): string {
  return handle && handle in EXIT_NAME_BY_HANDLE
    ? EXIT_NAME_BY_HANDLE[handle as CardinalHandle]
    : 'passage';
}

export function connectionHandles(
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

export function graphEdges(graph: AreaGraphData): Edge[] {
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
