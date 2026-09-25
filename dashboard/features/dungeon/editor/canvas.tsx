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
  type Node,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Map, PanelRightOpen, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GraphLayoutControls } from '@/features/graph/graph-layout-controls';
import {
  DEFAULT_SPACING,
  alignNodeCenterToGrid,
  alignedGridNodes,
  graphCenter,
  scaleAround,
  unscaleAround,
  type Point,
} from '@/features/graph/graph-layout';
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
  onLayoutComplete: () => void | Promise<void>;
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
  onLayoutComplete,
  onConnect,
  onCreateRoom,
  onCreateArea,
  onOpenInspector,
}: DungeonCanvasProps) {
  const [spacing, setSpacing] = useState(DEFAULT_SPACING);
  const [snapToGrid, setSnapToGrid] = useState(false);
  const spacingScale = spacing / 100;
  const centerPosition = useMemo(
    () => graphCenter(nodes),
    [nodes],
  );

  const displayNodes = useMemo(
    () => nodes.map((node) => ({
      ...node,
      position: scaleAround(node.position, centerPosition, spacingScale),
    })),
    [centerPosition.x, centerPosition.y, nodes, spacingScale],
  );

  const toLogicalPosition = useCallback(
    (position: Point) => unscaleAround(
      position,
      centerPosition,
      spacingScale,
    ),
    [centerPosition.x, centerPosition.y, spacingScale],
  );

  const snapDisplayPosition = useCallback(
    (nodeId: string, position: Point) => (
      snapToGrid
        ? alignNodeCenterToGrid(displayNodes, nodeId, position)
        : position
    ),
    [displayNodes, snapToGrid],
  );

  const handleNodesChange: OnNodesChange<Node<RoomNodeData>> = useCallback(
    (changes) => {
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

  const alignLocations = useCallback(async () => {
    const alignedNodes = alignedGridNodes(
      displayNodes,
      spacingScale,
      toLogicalPosition,
    );
    onNodesChange(
      alignedNodes.map((node) => ({
        type: 'position' as const,
        id: node.id,
        position: node.position,
      })),
    );
    for (const node of alignedNodes) {
      await onNodeDragStop(undefined, node);
    }
    await onLayoutComplete();
  }, [
    displayNodes,
    onLayoutComplete,
    onNodeDragStop,
    onNodesChange,
    spacingScale,
    toLogicalPosition,
  ]);

  return (
    <div className="graph-panel">
      {nodes.length ? (
        <>
        <ReactFlow
          nodes={displayNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={handleNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={(_, node) => onNodeSelect(node.id)}
          onEdgeClick={(_, edge) => onEdgeSelect(edge.id)}
          onNodeDragStop={(_, node) => {
            const displayPosition = snapDisplayPosition(
              node.id,
              node.position,
            );
            void onNodeDragStop(undefined, {
              ...node,
              position: toLogicalPosition(displayPosition),
            });
          }}
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
        <GraphLayoutControls
          snapToGrid={snapToGrid}
          onSnapToGridChange={setSnapToGrid}
          alignLabel="Align locations"
          alignDisabled={displayNodes.length <= 1}
          onAlign={alignLocations}
          spacing={spacing}
          onSpacingChange={setSpacing}
        />
        </>
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
