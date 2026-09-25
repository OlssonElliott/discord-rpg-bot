import {
  Handle,
  Position,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import { Flag, Skull, Users } from 'lucide-react';

import type { CombatLandmarkNodeData } from './combat-graph';

export function CombatLandmarkNode({
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
      <Handle id="top-left" type="source" position={Position.Top} style={{ left: 0 }} />
      <Handle id="top" type="source" position={Position.Top} />
      <Handle id="top-right" type="source" position={Position.Top} style={{ left: '100%' }} />
      <Handle id="right" type="source" position={Position.Right} />
      <Handle id="bottom-right" type="source" position={Position.Bottom} style={{ left: '100%' }} />
      <Handle id="bottom" type="source" position={Position.Bottom} />
      <Handle id="bottom-left" type="source" position={Position.Bottom} style={{ left: 0 }} />
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
