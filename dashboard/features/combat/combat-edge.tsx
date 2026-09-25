import {
  BaseEdge,
  EdgeLabelRenderer,
  type Edge,
  type EdgeProps,
} from '@xyflow/react';

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
    </>
  );
}
