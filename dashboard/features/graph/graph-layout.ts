import type { Node } from '@xyflow/react';

export const MIN_SPACING = 70;
export const MAX_SPACING = 160;
export const SPACING_STEP = 10;
export const DEFAULT_SPACING = 100;
export const SNAP_GRID_SIZE = 28;
export const FALLBACK_NODE_WIDTH = 178;
export const FALLBACK_NODE_HEIGHT = 76;

export type Point = { x: number; y: number };

export function scaleAround(
  point: Point,
  center: Point,
  scale: number,
): Point {
  return {
    x: center.x + (point.x - center.x) * scale,
    y: center.y + (point.y - center.y) * scale,
  };
}

export function unscaleAround(
  point: Point,
  center: Point,
  scale: number,
): Point {
  return {
    x: center.x + (point.x - center.x) / scale,
    y: center.y + (point.y - center.y) / scale,
  };
}

export function graphCenter<T extends Record<string, unknown>>(
  nodes: Node<T>[],
): Point {
  if (!nodes.length) return { x: 0, y: 0 };
  const total = nodes.reduce(
    (sum, node) => ({
      x: sum.x + node.position.x,
      y: sum.y + node.position.y,
    }),
    { x: 0, y: 0 },
  );
  return {
    x: total.x / nodes.length,
    y: total.y / nodes.length,
  };
}

export function alignNodeCenterToGrid<T extends Record<string, unknown>>(
  nodes: Node<T>[],
  nodeId: string,
  position: Point,
): Point {
  const node = nodes.find((candidate) => candidate.id === nodeId);
  const width = node?.measured?.width ?? FALLBACK_NODE_WIDTH;
  const height = node?.measured?.height ?? FALLBACK_NODE_HEIGHT;
  const centerX = position.x + width / 2;
  const centerY = position.y + height / 2;

  return {
    x: Math.round(centerX / SNAP_GRID_SIZE) * SNAP_GRID_SIZE - width / 2,
    y: Math.round(centerY / SNAP_GRID_SIZE) * SNAP_GRID_SIZE - height / 2,
  };
}

export function alignedGridNodes<T extends Record<string, unknown>>(
  displayNodes: Node<T>[],
  spacingScale: number,
  toLogicalPosition: (position: Point) => Point,
  horizontalDistance = SNAP_GRID_SIZE * 10,
  verticalDistance = SNAP_GRID_SIZE * 6,
): Node<T>[] {
  if (!displayNodes.length) return [];

  const center = graphCenter(displayNodes);
  const columns = Math.max(1, Math.ceil(Math.sqrt(displayNodes.length)));
  const rows = Math.ceil(displayNodes.length / columns);
  const slotCenters: Point[] = [];

  for (let row = 0; row < rows; row += 1) {
    const rowCount = Math.min(
      columns,
      displayNodes.length - row * columns,
    );
    for (let column = 0; column < rowCount; column += 1) {
      slotCenters.push({
        x: center.x
          + (column - (rowCount - 1) / 2)
            * horizontalDistance
            * spacingScale,
        y: center.y
          + (row - (rows - 1) / 2)
            * verticalDistance
            * spacingScale,
      });
    }
  }

  const nodeItems = displayNodes.map((node) => {
    const width = node.measured?.width ?? FALLBACK_NODE_WIDTH;
    const height = node.measured?.height ?? FALLBACK_NODE_HEIGHT;
    return {
      node,
      width,
      height,
      center: {
        x: node.position.x + width / 2,
        y: node.position.y + height / 2,
      },
    };
  });

  const availableNodeIds = new Set(nodeItems.map(({ node }) => node.id));
  const availableSlotIndexes = new Set(
    slotCenters.map((_, index) => index),
  );
  const assignments = new Map<string, number>();

  const candidates = nodeItems.flatMap((item) => (
    slotCenters.map((slot, slotIndex) => ({
      nodeId: item.node.id,
      slotIndex,
      distance: Math.hypot(
        item.center.x - slot.x,
        item.center.y - slot.y,
      ),
    }))
  )).sort((first, second) => (
    first.distance - second.distance
    || first.nodeId.localeCompare(second.nodeId)
    || first.slotIndex - second.slotIndex
  ));

  for (const candidate of candidates) {
    if (
      !availableNodeIds.has(candidate.nodeId)
      || !availableSlotIndexes.has(candidate.slotIndex)
    ) {
      continue;
    }
    assignments.set(candidate.nodeId, candidate.slotIndex);
    availableNodeIds.delete(candidate.nodeId);
    availableSlotIndexes.delete(candidate.slotIndex);
  }

  return nodeItems.map(({ node, width, height }) => {
    const slotIndex = assignments.get(node.id);
    if (slotIndex == null) return node;
    const slot = slotCenters[slotIndex];
    return {
      ...node,
      position: toLogicalPosition({
        x: slot.x - width / 2,
        y: slot.y - height / 2,
      }),
    };
  });
}
