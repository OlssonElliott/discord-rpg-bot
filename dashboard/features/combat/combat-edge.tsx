import {
  BaseEdge,
  EdgeLabelRenderer,
  type Edge,
  type EdgeProps,
} from '@xyflow/react';

import { Skull, UserRound } from 'lucide-react';

import type { CombatEdgeData } from './combat-graph';

export function CombatConnectionEdge({
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
  const labelOffsetX = data?.labelOffsetX ?? 0;
  const labelOffsetY = data?.labelOffsetY ?? 0;
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const length = Math.hypot(dx, dy) || 1;
  const normalX = -dy / length;
  const normalY = dx / length;

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
              transform: `translate(-50%, -50%) translate(${labelX + labelOffsetX}px, ${labelY + labelOffsetY}px)`,
            }}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
      {!!data?.travellers?.length && (
        <EdgeLabelRenderer>
          <>
            {data.travellers.map((traveller, index) => {
              const x = sourceX + dx * traveller.position;
              const y = sourceY + dy * traveller.position;
              const laneOffset = 22 + index * 24;
              return (
                <div
                  key={traveller.id}
                  className={[
                    'combat-edge-traveller',
                    traveller.kind === 'enemy'
                      ? 'combat-edge-traveller--enemy'
                      : 'combat-edge-traveller--character',
                    traveller.current
                      ? 'combat-edge-traveller--current'
                      : '',
                  ].filter(Boolean).join(' ')}
                  style={{
                    transform: `translate(-50%, -50%) translate(${x + normalX * laneOffset}px, ${y + normalY * laneOffset}px)`,
                  }}
                >
                  {traveller.kind === 'enemy'
                    ? <Skull size={12} />
                    : <UserRound size={12} />}
                  <strong>{traveller.name}</strong>
                  <small>{traveller.progress}/{traveller.cost}</small>
                </div>
              );
            })}
          </>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
