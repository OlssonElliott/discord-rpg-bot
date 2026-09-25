'use client';

import { useCallback, useMemo, useState } from 'react';
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
  combatEdgeTypes,
  combatNodeTypes,
  type CombatLandmarkNodeData,
} from './combat-graph';
import { GraphLayoutControls } from '@/features/graph/graph-layout-controls';
import {
  DEFAULT_SPACING,
  scaleAround,
  unscaleAround,
  type Point,
} from '@/features/graph/graph-layout';
import {
  alignDisplayPosition,
  alignedLandmarkNodes,
} from './combat-layout';

type CombatMapProps = {
  nodes: Node<CombatLandmarkNodeData>[];
  edges: Edge[];
  busy: boolean;
  onNodesChange: (changes: NodeChange<Node<CombatLandmarkNodeData>>[]) => void;
  onEdgesChange: (changes: EdgeChange<Edge>[]) => void;
  onNodeClick: (nodeId: string) => void;
  onNodeDragStart: (nodeId: string) => void;
  onNodeDragStop: (
    node: Node<CombatLandmarkNodeData>,
  ) => void | Promise<void>;
  onAutoConnectAll: () => Promise<boolean>;
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
  onNodeDragStart,
  onNodeDragStop,
  onAutoConnectAll,
  onConnect,
  onEdgeClick,
  onPaneClick,
}: CombatMapProps) {
  const [spacing, setSpacing] = useState(DEFAULT_SPACING);
  const [snapToGrid, setSnapToGrid] = useState(false);
  const spacingScale = spacing / 100;
  const centerPosition = nodes.find(
    (node) => node.id === 'room:center',
  )?.position ?? { x: 500, y: 350 };

  const displayNodes = useMemo(
    () => nodes.map((node) => ({
      ...node,
      position: node.id === 'room:center'
        ? node.position
        : scaleAround(node.position, centerPosition, spacingScale),
    })),
    [centerPosition.x, centerPosition.y, nodes, spacingScale],
  );

  const alignNodePosition = useCallback(
    (nodeId: string, position: Point) => (
      alignDisplayPosition(displayNodes, nodeId, position)
    ),
    [displayNodes],
  );

  const snapDisplayPosition = useCallback(
    (nodeId: string, position: Point) => (
      snapToGrid
        ? alignNodePosition(nodeId, position)
        : position
    ),
    [alignNodePosition, snapToGrid],
  );

  const toLogicalPosition = useCallback(
    (position: Point) => unscaleAround(
      position,
      centerPosition,
      spacingScale,
    ),
    [centerPosition.x, centerPosition.y, spacingScale],
  );

  const handleNodesChange = useCallback(
    (changes: NodeChange<Node<CombatLandmarkNodeData>>[]) => {
      onNodesChange(
        changes.map((change) => (
          change.type === 'position' && change.position
            ? {
                ...change,
                position: toLogicalPosition(
                  snapDisplayPosition(change.id, change.position),
                ),
              }
            : change
        )),
      );
    },
    [onNodesChange, snapDisplayPosition, toLogicalPosition],
  );

  const alignLandmarks = useCallback(async () => {
    const alignedNodes = alignedLandmarkNodes(
      displayNodes,
      spacingScale,
      toLogicalPosition,
    );
    for (const node of alignedNodes) {
      await onNodeDragStop(node);
    }
    await onAutoConnectAll();
  }, [
    displayNodes,
    onAutoConnectAll,
    onNodeDragStop,
    spacingScale,
    toLogicalPosition,
  ]);

  return (
    <div className="combat-board">
      <ReactFlow
        nodes={displayNodes}
        edges={edges}
        nodeTypes={combatNodeTypes}
        edgeTypes={combatEdgeTypes}
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => onNodeClick(node.id)}
        onNodeDragStart={(_, node) => onNodeDragStart(node.id)}
        onNodeDragStop={(_, node) => {
          const displayPosition = snapDisplayPosition(node.id, node.position);
          onNodeDragStop({
            ...node,
            position: node.id === 'room:center'
              ? displayPosition
              : toLogicalPosition(displayPosition),
          });
        }}
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
      <GraphLayoutControls
        snapToGrid={snapToGrid}
        onSnapToGridChange={setSnapToGrid}
        alignLabel="Align landmarks"
        alignDisabled={busy || displayNodes.length <= 1}
        onAlign={alignLandmarks}
        spacing={spacing}
        onSpacingChange={setSpacing}
      />
      <div className="combat-board__hint">
        Drag landmarks to arrange · Drag a handle to connect · Click a connection to edit
      </div>
    </div>
  );
}
