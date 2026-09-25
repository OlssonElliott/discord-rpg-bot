import {
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import { Flag, Skull, Users } from 'lucide-react';

import type {
  CombatLandmarkData,
  CombatSceneData,
  CombatantData,
} from '@/lib/api';

const SAFE_FALLBACK_POSITIONS = [
  { x: 0.12, y: 0.18 },
  { x: 0.80, y: 0.18 },
  { x: 0.12, y: 0.82 },
  { x: 0.80, y: 0.82 },
  { x: 0.12, y: 0.34 },
  { x: 0.80, y: 0.34 },
  { x: 0.12, y: 0.66 },
  { x: 0.80, y: 0.66 },
  { x: 0.32, y: 0.34 },
  { x: 0.60, y: 0.34 },
  { x: 0.32, y: 0.66 },
  { x: 0.60, y: 0.66 },
];

function fallbackPosition(index: number) {
  if (index === 0) return { x: 0.5, y: 0.5 };
  return SAFE_FALLBACK_POSITIONS[
    (index - 1) % SAFE_FALLBACK_POSITIONS.length
  ];
}

export function clamp(value: number) {
  return Math.min(0.94, Math.max(0.06, value));
}

export const COMBAT_LAYOUT_WIDTH = 1000;
export const COMBAT_LAYOUT_HEIGHT = 700;

export type CombatLandmarkNodeData = {
  landmark: CombatLandmarkData;
  combatants: CombatantData[];
} & Record<string, unknown>;

type CombatEdgeData = {
  label: string;
  showLabel: boolean;
  labelPosition: number;
} & Record<string, unknown>;

type LandmarkHandle =
  | 'top-left'
  | 'top'
  | 'top-right'
  | 'right'
  | 'bottom-right'
  | 'bottom'
  | 'bottom-left'
  | 'left';

export function routeKey(sourceId: string, destinationId: string) {
  return [sourceId, destinationId].sort().join('::');
}

export function combatantKey(combatant: CombatantData) {
  return `${combatant.kind}:${combatant.source_id}`;
}

const HANDLE_ANGLES: Array<{ handle: LandmarkHandle; angle: number }> = [
  { handle: 'right', angle: 0 },
  { handle: 'bottom-right', angle: Math.PI / 4 },
  { handle: 'bottom', angle: Math.PI / 2 },
  { handle: 'bottom-left', angle: Math.PI * 3 / 4 },
  { handle: 'left', angle: Math.PI },
  { handle: 'top-left', angle: -Math.PI * 3 / 4 },
  { handle: 'top', angle: -Math.PI / 2 },
  { handle: 'top-right', angle: -Math.PI / 4 },
];

function angleDistance(first: number, second: number) {
  const difference = Math.abs(first - second) % (Math.PI * 2);
  return Math.min(difference, Math.PI * 2 - difference);
}

function routeHandleAssignments(
  scene: CombatSceneData,
  positions: Map<string, { x: number; y: number }>,
): Map<string, { sourceHandle?: LandmarkHandle; targetHandle?: LandmarkHandle }> {
  const assignments = new Map<
    string,
    { sourceHandle?: LandmarkHandle; targetHandle?: LandmarkHandle }
  >();

  for (const landmark of scene.landmarks) {
    const sourcePosition = positions.get(landmark.id);
    if (!sourcePosition) continue;

    const incident = scene.routes
      .filter(
        (route) => (
          route.source_landmark_id === landmark.id
          || route.destination_landmark_id === landmark.id
        ),
      )
      .map((route) => {
        const otherId = route.source_landmark_id === landmark.id
          ? route.destination_landmark_id
          : route.source_landmark_id;
        const otherPosition = positions.get(otherId);
        if (!otherPosition) return null;
        return {
          route,
          key: routeKey(
            route.source_landmark_id,
            route.destination_landmark_id,
          ),
          angle: Math.atan2(
            otherPosition.y - sourcePosition.y,
            otherPosition.x - sourcePosition.x,
          ),
        };
      })
      .filter((item): item is NonNullable<typeof item> => item !== null)
      .sort((first, second) => (
        first.angle - second.angle
        || first.key.localeCompare(second.key)
      ));

    const available = new Set(HANDLE_ANGLES.map(({ handle }) => handle));

    for (const item of incident) {
      const orderedHandles = HANDLE_ANGLES
        .slice()
        .sort((first, second) => (
          angleDistance(item.angle, first.angle)
          - angleDistance(item.angle, second.angle)
        ));
      const chosen = orderedHandles.find(({ handle }) => available.has(handle))
        ?? orderedHandles[0];
      available.delete(chosen.handle);

      const current = assignments.get(item.key) ?? {};
      if (item.route.source_landmark_id === landmark.id) {
        current.sourceHandle = chosen.handle;
      } else {
        current.targetHandle = chosen.handle;
      }
      assignments.set(item.key, current);
    }
  }

  return assignments;
}

function CombatLandmarkNode({
  data,
  selected,
}: NodeProps<Node<CombatLandmarkNodeData>>) {
  const { landmark, combatants } = data;
  const kind = landmark.synthetic
    ? 'Anchor'
    : landmark.feature_type === 'door'
      ? 'Door'
      : 'Landmark';

  return (
    <article
      className={[
        'combat-landmark-node',
        landmark.synthetic ? 'combat-landmark-node--synthetic' : '',
        landmark.feature_type === 'door' ? 'combat-landmark-node--door' : '',
        selected ? 'combat-landmark-node--selected' : '',
      ].filter(Boolean).join(' ')}
    >
      <Handle
        id="top-left"
        type="source"
        position={Position.Top}
        style={{ left: 0 }}
      />
      <Handle id="top" type="source" position={Position.Top} />
      <Handle
        id="top-right"
        type="source"
        position={Position.Top}
        style={{ left: '100%' }}
      />
      <Handle id="right" type="source" position={Position.Right} />
      <Handle
        id="bottom-right"
        type="source"
        position={Position.Bottom}
        style={{ left: '100%' }}
      />
      <Handle id="bottom" type="source" position={Position.Bottom} />
      <Handle
        id="bottom-left"
        type="source"
        position={Position.Bottom}
        style={{ left: 0 }}
      />
      <Handle id="left" type="source" position={Position.Left} />
      <div className="combat-landmark-node__eyebrow">{kind}</div>
      <div className="combat-landmark-node__title">
        <Flag size={14} />
        <strong>{landmark.name}</strong>
      </div>
      {landmark.feature_type && landmark.feature_type !== 'door' && (
        <span className="combat-landmark-node__type">{landmark.feature_type}</span>
      )}
      {landmark.source_connection_id && (
        <span className="combat-landmark-node__type">linked room exit</span>
      )}
      <div className="combat-landmark-node__occupants">
        {combatants.map((combatant) => (
          <span
            key={`${combatant.kind}:${combatant.source_id}`}
            className={[
              'combat-token',
              `combat-token--${combatant.kind}`,
              combatant.is_current_turn ? 'combat-token--current' : '',
            ].filter(Boolean).join(' ')}
          >
            {combatant.kind === 'character' ? <Users size={12} /> : <Skull size={12} />}
            {combatant.name}
            {combatant.is_current_turn && <small>TURN</small>}
            {!combatant.is_current_turn && combatant.relation !== 'at' && (
              <small>{combatant.relation}</small>
            )}
          </span>
        ))}
      </div>
    </article>
  );
}

function CombatConnectionEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  markerEnd,
  markerStart,
  style,
  interactionWidth,
  data,
}: EdgeProps<Edge<CombatEdgeData>>) {
  const edgePath = `M ${sourceX},${sourceY} L ${targetX},${targetY}`;
  const position = data?.labelPosition ?? 0.5;
  const labelX = sourceX + (targetX - sourceX) * position;
  const labelY = sourceY + (targetY - sourceY) * position;

  return (
    <>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        markerStart={markerStart}
        style={style}
        interactionWidth={interactionWidth}
      />
      {data?.showLabel && data.label && (
        <EdgeLabelRenderer>
          <div
            className="combat-edge-label"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const combatNodeTypes = { landmark: CombatLandmarkNode };
export const combatEdgeTypes = { combat: CombatConnectionEdge };

export function combatNodes(
  scene: CombatSceneData,
  selectedLandmarkId: string | null,
): Node<CombatLandmarkNodeData>[] {
  return scene.landmarks.map((landmark, index) => {
    const fallback = fallbackPosition(index);
    const x = landmark.x ?? fallback.x;
    const y = landmark.y ?? fallback.y;
    return {
      id: landmark.id,
      type: 'landmark',
      position: {
        x: x * COMBAT_LAYOUT_WIDTH,
        y: y * COMBAT_LAYOUT_HEIGHT,
      },
      selected: landmark.id === selectedLandmarkId,
      data: {
        landmark,
        combatants: scene.combatants.filter(
          (combatant) => (
            !combatant.is_between_landmarks
            && combatant.landmark_id === landmark.id
          ),
        ),
      },
    };
  });
}

type EdgeDraft = {
  edge: Edge<CombatEdgeData>;
  sourcePoint: { x: number; y: number };
  targetPoint: { x: number; y: number };
};

function nodeCenter(node: Node<CombatLandmarkNodeData>) {
  const width = node.measured?.width ?? 178;
  const height = node.measured?.height ?? 76;
  return {
    x: node.position.x + width / 2,
    y: node.position.y + height / 2,
  };
}

function segmentsCross(
  firstSource: { x: number; y: number },
  firstTarget: { x: number; y: number },
  secondSource: { x: number; y: number },
  secondTarget: { x: number; y: number },
): boolean {
  const orientation = (
    a: { x: number; y: number },
    b: { x: number; y: number },
    c: { x: number; y: number },
  ) => (
    (b.x - a.x) * (c.y - a.y)
    - (b.y - a.y) * (c.x - a.x)
  );
  const a = orientation(firstSource, firstTarget, secondSource);
  const b = orientation(firstSource, firstTarget, secondTarget);
  const c = orientation(secondSource, secondTarget, firstSource);
  const d = orientation(secondSource, secondTarget, firstTarget);
  const epsilon = 1e-9;
  return a * b < -epsilon && c * d < -epsilon;
}

export function combatEdges(
  scene: CombatSceneData,
  nodes: Node<CombatLandmarkNodeData>[],
  selectedRouteId: string | null,
): Edge[] {
  const nodesById = new globalThis.Map(nodes.map((node) => [node.id, node]));
  const positions = new globalThis.Map(
    nodes.map((node) => [node.id, node.position]),
  );
  const handleAssignments = routeHandleAssignments(scene, positions);

  const drafts: EdgeDraft[] = scene.routes.map((route) => {
    const id = routeKey(
      route.source_landmark_id,
      route.destination_landmark_id,
    );
    const travellers = scene.combatants.filter(
      (combatant) => (
        combatant.is_between_landmarks
        && combatant.route_source_landmark_id
        && combatant.route_destination_landmark_id
        && routeKey(
          combatant.route_source_landmark_id,
          combatant.route_destination_landmark_id,
        ) === id
      ),
    );
    const travellerLabel = travellers
      .map((combatant) => (
        `${combatant.name} ${combatant.route_progress}/${combatant.route_cost}`
      ))
      .join(', ');
    const routeLabel = route.blocked
      ? `${route.distance} · move ${route.movement_cost} · blocked`
      : `${route.distance} · move ${route.movement_cost}`;
    const label = travellerLabel
      ? `${routeLabel} · ${travellerLabel}`
      : routeLabel;

    const sourceNode = nodesById.get(route.source_landmark_id);
    const targetNode = nodesById.get(route.destination_landmark_id);
    const sourcePoint = sourceNode
      ? nodeCenter(sourceNode)
      : positions.get(route.source_landmark_id) ?? { x: 0, y: 0 };
    const targetPoint = targetNode
      ? nodeCenter(targetNode)
      : positions.get(route.destination_landmark_id) ?? { x: 0, y: 0 };

    return {
      sourcePoint,
      targetPoint,
      edge: {
        id,
        source: route.source_landmark_id,
        target: route.destination_landmark_id,
        ...handleAssignments.get(id),
        type: 'combat',
        selected: id === selectedRouteId,
        data: {
          label,
          showLabel: true,
          labelPosition: 0.5,
        },
        className: [
          'combat-connection-edge',
          route.blocked ? 'combat-connection-edge--blocked' : '',
          travellers.length ? 'combat-connection-edge--occupied' : '',
        ].filter(Boolean).join(' '),
      },
    };
  });

  for (let i = 0; i < drafts.length; i += 1) {
    for (let j = i + 1; j < drafts.length; j += 1) {
      const first = drafts[i];
      const second = drafts[j];
      if (
        first.edge.source === second.edge.source
        || first.edge.source === second.edge.target
        || first.edge.target === second.edge.source
        || first.edge.target === second.edge.target
      ) {
        continue;
      }
      if (!segmentsCross(
        first.sourcePoint,
        first.targetPoint,
        second.sourcePoint,
        second.targetPoint,
      )) {
        continue;
      }

      const firstData = first.edge.data;
      const secondData = second.edge.data;
      if (!firstData || !secondData) continue;

      if (firstData.label === secondData.label) {
        if (first.edge.id.localeCompare(second.edge.id) <= 0) {
          secondData.showLabel = false;
        } else {
          firstData.showLabel = false;
        }
      } else {
        const firstEarlier = first.edge.id.localeCompare(second.edge.id) <= 0;
        firstData.labelPosition = firstEarlier ? 0.34 : 0.66;
        secondData.labelPosition = firstEarlier ? 0.66 : 0.34;
      }
    }
  }

  return drafts.map(({ edge }) => edge);
}
