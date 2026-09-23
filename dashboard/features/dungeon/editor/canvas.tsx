'use client';

import {
  Background,
  ConnectionMode,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type Edge,
  type Node,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Map, PanelRightOpen, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { nodeTypes, type RoomNodeData } from './graph';

type DungeonCanvasProps = {
  nodes: Node<RoomNodeData>[];
  edges: Edge[];
  areaId: string;
  inspectorOpen: boolean;
  onNodesChange: OnNodesChange<Node<RoomNodeData>>;
  onEdgesChange: OnEdgesChange<Edge>;
  onNodeSelect: (nodeId: string) => void;
  onEdgeSelect: (edgeId: string) => void;
  onNodeDragStop: (event: unknown, node: Node<RoomNodeData>) => void | Promise<void>;
  onConnect: (connection: Connection) => void;
  onCreateRoom: () => void;
  onCreateArea: () => void;
  onOpenInspector: () => void;
};

export function DungeonCanvas({
  nodes,
  edges,
  areaId,
  inspectorOpen,
  onNodesChange,
  onEdgesChange,
  onNodeSelect,
  onEdgeSelect,
  onNodeDragStop,
  onConnect,
  onCreateRoom,
  onCreateArea,
  onOpenInspector,
}: DungeonCanvasProps) {
  return (
    <div className="graph-panel">
      {nodes.length ? (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={(_, node) => onNodeSelect(node.id)}
          onEdgeClick={(_, edge) => onEdgeSelect(edge.id)}
          onNodeDragStop={onNodeDragStop}
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
          <Button onClick={areaId ? onCreateRoom : onCreateArea}>
            <Plus /> {areaId ? 'Add location' : 'Create area'}
          </Button>
        </div>
      )}
      <div className="canvas-hint">Drag to pan · Scroll to zoom · Drag a handle to connect</div>
      {!inspectorOpen && (
        <Button
          className="inspector-reopen"
          variant="outline"
          size="sm"
          onClick={onOpenInspector}
          title="Open inspector"
        >
          <PanelRightOpen />
          Inspector
        </Button>
      )}
    </div>
  );
}
