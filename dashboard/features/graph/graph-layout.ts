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

type AxisCluster = {
  center: number;
  values: number[];
};

function clusterAxis(
  values: number[],
  threshold: number,
): AxisCluster[] {
  const sorted = [...values].sort((a, b) => a - b);
  const clusters: AxisCluster[] = [];

  for (const value of sorted) {
    const current = clusters.at(-1);
    if (!current || Math.abs(value - current.center) > threshold) {
      clusters.push({ center: value, values: [value] });
      continue;
    }
    current.values.push(value);
    current.center = (
      current.values.reduce((sum, item) => sum + item, 0)
      / current.values.length
    );
  }

  return clusters;
}

function nearestClusterIndex(
  clusters: AxisCluster[],
  value: number,
): number {
  return clusters.reduce(
    (bestIndex, cluster, index) => (
      Math.abs(value - cluster.center)
        < Math.abs(value - clusters[bestIndex].center)
        ? index
        : bestIndex
    ),
    0,
  );
}

export function alignedGridNodes<T extends Record<string, unknown>>(
  displayNodes: Node<T>[],
  spacingScale: number,
  toLogicalPosition: (position: Point) => Point,
  horizontalDistance = SNAP_GRID_SIZE * 12,
  verticalDistance = SNAP_GRID_SIZE * 8,
): Node<T>[] {
  if (!displayNodes.length) return [];

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

  // Locations are free-form graphs. Align should tidy the structure the DM
  // already made, not replace it with a new compact sqrt(n) layout.
  const xClusters = clusterAxis(
    nodeItems.map((item) => item.center.x),
    SNAP_GRID_SIZE * 5,
  );
  const yClusters = clusterAxis(
    nodeItems.map((item) => item.center.y),
    SNAP_GRID_SIZE * 4,
  );

  const currentCenter = {
    x: nodeItems.reduce((sum, item) => sum + item.center.x, 0)
      / nodeItems.length,
    y: nodeItems.reduce((sum, item) => sum + item.center.y, 0)
      / nodeItems.length,
  };

  const xSpan = xClusters.length > 1
    ? xClusters.at(-1)!.center - xClusters[0].center
    : 0;
  const ySpan = yClusters.length > 1
    ? yClusters.at(-1)!.center - yClusters[0].center
    : 0;

  const xSpacing = xClusters.length > 1
    ? Math.max(
        horizontalDistance * spacingScale,
        xSpan / (xClusters.length - 1),
      )
    : 0;
  const ySpacing = yClusters.length > 1
    ? Math.max(
        verticalDistance * spacingScale,
        ySpan / (yClusters.length - 1),
      )
    : 0;

  const targetX = xClusters.map((_, index) => (
    currentCenter.x
    + (index - (xClusters.length - 1) / 2) * xSpacing
  ));
  const targetY = yClusters.map((_, index) => (
    currentCenter.y
    + (index - (yClusters.length - 1) / 2) * ySpacing
  ));

  return nodeItems.map(({ node, width, height, center }) => {
    const column = nearestClusterIndex(xClusters, center.x);
    const row = nearestClusterIndex(yClusters, center.y);
    return {
      ...node,
      position: toLogicalPosition({
        x: targetX[column] - width / 2,
        y: targetY[row] - height / 2,
      }),
    };
  });
}
