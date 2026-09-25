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
  onNodeDragStop: (
    node: Node<CombatLandmarkNodeData>,
  ) => void | Promise<void>;
  onConnect: (connection: Connection) => void;
  onEdgeClick: (sourceId: string, targetId: string) => void;
  onPaneClick: () => void;
};

const MIN_SPACING = 70;
const MAX_SPACING = 160;
const SPACING_STEP = 10;
const DEFAULT_SPACING = 100;
const SNAP_GRID_SIZE = 28;
const FALLBACK_NODE_WIDTH = 178;
const FALLBACK_NODE_HEIGHT = 76;

type Point = { x: number; y: number };

function scaleAround(
  point: Point,
  center: Point,
  scale: number,
): Point {
  return {
    x: center.x + (point.x - center.x) * scale,
    y: center.y + (point.y - center.y) * scale,
  };
}

function unscaleAround(
  point: Point,
  center: Point,
  scale: number,
): Point {
  return {
    x: center.x + (point.x - center.x) / scale,
    y: center.y + (point.y - center.y) / scale,
  };
}

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

  const alignDisplayPosition = useCallback(
    (nodeId: string, position: Point) => {
      const node = displayNodes.find((candidate) => candidate.id === nodeId);
      const width = node?.measured?.width ?? FALLBACK_NODE_WIDTH;
      const height = node?.measured?.height ?? FALLBACK_NODE_HEIGHT;
      const centerX = position.x + width / 2;
      const centerY = position.y + height / 2;

      return {
        x: Math.round(centerX / SNAP_GRID_SIZE) * SNAP_GRID_SIZE - width / 2,
        y: Math.round(centerY / SNAP_GRID_SIZE) * SNAP_GRID_SIZE - height / 2,
      };
    },
    [displayNodes],
  );

  const snapDisplayPosition = useCallback(
    (nodeId: string, position: Point) => (
      snapToGrid
        ? alignDisplayPosition(nodeId, position)
        : position
    ),
    [alignDisplayPosition, snapToGrid],
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

  const adjustSpacing = useCallback((delta: number) => {
    setSpacing((current) => Math.min(
      MAX_SPACING,
      Math.max(MIN_SPACING, current + delta),
    ));
  }, []);

  const alignLandmarks = useCallback(async () => {
    const alignedNodes = displayNodes
      .filter((node) => node.id !== 'room:center')
      .map((node) => ({
        ...node,
        position: toLogicalPosition(
          alignDisplayPosition(node.id, node.position),
        ),
      }));

    for (const node of alignedNodes) {
      await onNodeDragStop(node);
    }
  }, [
    alignDisplayPosition,
    displayNodes,
    onNodeDragStop,
    toLogicalPosition,
  ]);

  return (
    <div className="combat-board">
      <ReactFlow
        nodes={displayNodes}
        edges={edges}
        nodeTypes={combatNodeTypes}
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => onNodeClick(node.id)}
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
      <div className="combat-map-layout-control">
        <div className="combat-map-layout-control__title">Map layout</div>
        <button
          type="button"
          className="combat-map-layout-control__snap"
          aria-pressed={snapToGrid}
          onClick={() => setSnapToGrid((enabled) => !enabled)}
        >
          <span>Snap to grid</span>
          <span
            className={[
              'combat-map-layout-control__switch',
              snapToGrid ? 'combat-map-layout-control__switch--on' : '',
            ].filter(Boolean).join(' ')}
            aria-hidden="true"
          >
            <span />
          </span>
        </button>
        <button
          type="button"
          className="combat-map-layout-control__align"
          disabled={busy || displayNodes.length <= 1}
          onClick={() => void alignLandmarks()}
        >
          Align landmarks
        </button>
        <div className="combat-spacing-control">
          <div className="combat-spacing-control__heading">
            <span>Spacing</span>
            <button
              type="button"
              onClick={() => setSpacing(DEFAULT_SPACING)}
              title="Reset spacing to 100%"
            >
              {spacing}%
            </button>
          </div>
          <div className="combat-spacing-control__controls">
            <button
              type="button"
              aria-label="Decrease map spacing"
              disabled={spacing <= MIN_SPACING}
              onClick={() => adjustSpacing(-SPACING_STEP)}
            >
              −
            </button>
            <input
              type="range"
              aria-label="Map spacing"
              min={MIN_SPACING}
              max={MAX_SPACING}
              step={SPACING_STEP}
              value={spacing}
              onChange={(event) => setSpacing(Number(event.target.value))}
            />
            <button
              type="button"
              aria-label="Increase map spacing"
              disabled={spacing >= MAX_SPACING}
              onClick={() => adjustSpacing(SPACING_STEP)}
            >
              +
            </button>
          </div>
        </div>
      </div>
      <div className="combat-board__hint">
        Drag landmarks to arrange · Drag a handle to connect · Click a connection to edit
      </div>
    </div>
  );
}
