'use client';

import {
  Background,
  ConnectionMode,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from '@xyflow/react';

import {
  combatNodeTypes,
  type CombatLandmarkNodeData,
} from './combat-graph';

type CombatMapProps = {
  nodes: Node<CombatLandmarkNodeData>[];
  edges: Edge[];
  busy: boolean;
  onNodesChange: (changes: NodeChange<Node<CombatLandmarkNodeData>>[]) => void;
  onEdgesChange: (changes: EdgeChange<Edge>[]) => void;
  onNodeClick: (nodeId: string) => void;
  onNodeDragStop: (node: Node<CombatLandmarkNodeData>) => void;
  onConnect: (connection: Connection) => void;
  onEdgeClick: (sourceId: string, targetId: string) => void;
  onPaneClick: () => void;
};

export function CombatMap({
  nodes,
  edges,
  busy,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
  onNodeDragStop,
  onConnect,
  onEdgeClick,
  onPaneClick,
}: CombatMapProps) {
  return (
    <div className="combat-board">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={combatNodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => onNodeClick(node.id)}
        onNodeDragStop={(_, node) => onNodeDragStop(node)}
        onConnect={onConnect}
        onEdgeClick={(_, edge) => onEdgeClick(edge.source, edge.target)}
        onPaneClick={onPaneClick}
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
  );
}
