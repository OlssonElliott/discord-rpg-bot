import type { Node } from '@xyflow/react';

import type { CombatLandmarkNodeData } from './combat-graph';

export const MIN_SPACING = 70;
export const MAX_SPACING = 160;
export const SPACING_STEP = 10;
export const DEFAULT_SPACING = 100;
export const SNAP_GRID_SIZE = 28;
export const FALLBACK_NODE_WIDTH = 178;
export const FALLBACK_NODE_HEIGHT = 76;
export const ALIGN_HORIZONTAL_DISTANCE = SNAP_GRID_SIZE * 12;
export const ALIGN_VERTICAL_DISTANCE = SNAP_GRID_SIZE * 8;

export type Point = { x: number; y: number };

type AlignmentSlot = {
  x: number;
  y: number;
  angle: number;
};

const CORNER_ALIGNMENT_SLOTS: Record<string, Point> = {
  'room:corner:nw': { x: -1, y: -1 },
  'room:corner:ne': { x: 1, y: -1 },
  'room:corner:se': { x: 1, y: 1 },
  'room:corner:sw': { x: -1, y: 1 },
};

function angularDistance(first: number, second: number): number {
  const difference = Math.abs(first - second) % (Math.PI * 2);
  return Math.min(difference, Math.PI * 2 - difference);
}

function alignmentSlots(count: number): AlignmentSlot[] {
  const divisions = Math.max(2, Math.ceil(count / 4));
  const coordinates = Array.from(
    { length: divisions + 1 },
    (_, index) => -1 + (index * 2) / divisions,
  );
  const positions: Point[] = [];

  for (const x of coordinates) {
    positions.push({ x, y: -1 });
  }
  for (const y of coordinates.slice(1, -1)) {
    positions.push({ x: 1, y });
  }
  for (const x of [...coordinates].reverse()) {
    positions.push({ x, y: 1 });
  }
  for (const y of [...coordinates].reverse().slice(1, -1)) {
    positions.push({ x: -1, y });
  }

  return positions.map((position) => ({
    ...position,
    angle: Math.atan2(position.y, position.x),
  }));
}

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

export function alignDisplayPosition(
  nodes: Node<CombatLandmarkNodeData>[],
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

export function alignedLandmarkNodes(
  displayNodes: Node<CombatLandmarkNodeData>[],
  spacingScale: number,
  toLogicalPosition: (position: Point) => Point,
): Node<CombatLandmarkNodeData>[] {
  const centerNode = displayNodes.find((node) => node.id === 'room:center');
  const outerNodes = displayNodes.filter((node) => node.id !== 'room:center');
  if (!centerNode || !outerNodes.length) return [];

  const centerWidth = centerNode.measured?.width ?? FALLBACK_NODE_WIDTH;
  const centerHeight = centerNode.measured?.height ?? FALLBACK_NODE_HEIGHT;
  const centerPoint = {
    x: centerNode.position.x + centerWidth / 2,
    y: centerNode.position.y + centerHeight / 2,
  };

  const availableSlots = alignmentSlots(outerNodes.length);
  const nodeItems = outerNodes.map((node) => {
    const width = node.measured?.width ?? FALLBACK_NODE_WIDTH;
    const height = node.measured?.height ?? FALLBACK_NODE_HEIGHT;
    return {
      node,
      width,
      height,
      angle: Math.atan2(
        node.position.y + height / 2 - centerPoint.y,
        node.position.x + width / 2 - centerPoint.x,
      ),
    };
  });

  const assignments: Array<
    (typeof nodeItems)[number] & { slot: AlignmentSlot }
  > = [];

  for (const item of nodeItems) {
    const fixed = CORNER_ALIGNMENT_SLOTS[item.node.id];
    if (!fixed) continue;
    const slotIndex = availableSlots.findIndex(
      (slot) => slot.x === fixed.x && slot.y === fixed.y,
    );
    if (slotIndex < 0) continue;
    const [slot] = availableSlots.splice(slotIndex, 1);
    assignments.push({ ...item, slot });
  }

  const assignedIds = new Set(assignments.map(({ node }) => node.id));
  const remainingNodes = nodeItems
    .filter(({ node }) => !assignedIds.has(node.id))
    .sort((first, second) => first.angle - second.angle);

  for (const item of remainingNodes) {
    if (!availableSlots.length) break;
    const closestIndex = availableSlots.reduce(
      (bestIndex, slot, index) => (
        angularDistance(item.angle, slot.angle)
          < angularDistance(item.angle, availableSlots[bestIndex].angle)
          ? index
          : bestIndex
      ),
      0,
    );
    const [slot] = availableSlots.splice(closestIndex, 1);
    assignments.push({ ...item, slot });
  }

  return assignments.map(({ node, width, height, slot }) => {
    const displayPosition = {
      x: centerPoint.x
        + slot.x * ALIGN_HORIZONTAL_DISTANCE * spacingScale
        - width / 2,
      y: centerPoint.y
        + slot.y * ALIGN_VERTICAL_DISTANCE * spacingScale
        - height / 2,
    };
    return {
      ...node,
      position: toLogicalPosition(displayPosition),
    };
  });
}
