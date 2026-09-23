'use client';

import { CombatWorkspace } from './workspace';
import type {
  CombatSceneData,
  EnemyTemplateData,
  RoomData,
} from '@/lib/api';

type UpdateCombat = (
  path: string,
  init: RequestInit,
  message: string,
) => Promise<boolean>;

type CombatWorkspaceControllerProps = {
  scene: CombatSceneData | null;
  rooms: RoomData[];
  enemyTemplates: EnemyTemplateData[];
  preferredRoomId: string | null;
  busy: boolean;
  onStart: (roomId: string) => Promise<boolean>;
  onEnd: () => Promise<boolean>;
  onRefresh: () => Promise<void>;
  updateCombat: UpdateCombat;
};

export function CombatWorkspaceController({
  scene,
  rooms,
  enemyTemplates,
  preferredRoomId,
  busy,
  onStart,
  onEnd,
  onRefresh,
  updateCombat,
}: CombatWorkspaceControllerProps) {
  return (
    <CombatWorkspace
      scene={scene}
      rooms={rooms}
      enemyTemplates={enemyTemplates}
      preferredRoomId={preferredRoomId}
      busy={busy}
      onStart={onStart}
      onEnd={onEnd}
      onRefresh={onRefresh}
      onPositionLandmark={(landmarkId, x, y) => updateCombat(
        `/combat/landmarks/${landmarkId}`,
        {
          method: 'PATCH',
          body: JSON.stringify({ x, y }),
        },
        'Landmark position saved',
      )}
      onMoveCombatant={(combatant, landmarkId, relation) => updateCombat(
        `/combat/movement/${combatant.kind}/${combatant.source_id}`,
        {
          method: 'PATCH',
          body: JSON.stringify({ landmark_id: landmarkId, relation }),
        },
        `${combatant.name} moved`,
      )}
      onAddEnemy={(templateId, landmarkId, quantity) => updateCombat(
        '/combat/enemies',
        {
          method: 'POST',
          body: JSON.stringify({
            template_id: templateId,
            landmark_id: landmarkId,
            quantity,
          }),
        },
        `${quantity} enem${quantity === 1 ? 'y' : 'ies'} added`,
      )}
      onRemoveEnemy={(enemyId) => updateCombat(
        `/combat/combatants/enemy/${enemyId}`,
        { method: 'DELETE' },
        'Enemy removed from combat',
      )}
      onAttack={(attacker, targetId) => updateCombat(
        attacker.kind === 'character'
          ? '/combat/actions/attack'
          : '/combat/actions/enemy-attack',
        {
          method: 'POST',
          body: JSON.stringify(
            attacker.kind === 'character'
              ? { target_enemy_id: targetId }
              : { target_character_id: targetId },
          ),
        },
        'Attack resolved',
      )}
      onNextTurn={() => updateCombat(
        '/combat/turn/next',
        { method: 'POST' },
        'Turn advanced',
      )}
      onPreviousTurn={() => updateCombat(
        '/combat/turn/previous',
        { method: 'POST' },
        'Turn moved back',
      )}
      onSetInitiative={(combatant, initiativeScore) => updateCombat(
        `/combat/initiative/${combatant.kind}/${combatant.source_id}`,
        {
          method: 'PATCH',
          body: JSON.stringify({ initiative_score: initiativeScore }),
        },
        `${combatant.name}'s initiative updated`,
      )}
      onConnectLandmarks={(sourceId, destinationId, distance, obstacle, blocked) => updateCombat(
        '/combat/routes',
        {
          method: 'PUT',
          body: JSON.stringify({
            source_landmark_id: sourceId,
            destination_landmark_id: destinationId,
            distance,
            obstacle,
            blocked,
          }),
        },
        'Combat connection saved',
      )}
      onDeleteLandmark={(landmarkId) => updateCombat(
        `/combat/landmarks/${landmarkId}`,
        { method: 'DELETE' },
        'Landmark removed',
      )}
      onDeleteConnection={(sourceId, destinationId) => updateCombat(
        '/combat/routes',
        {
          method: 'DELETE',
          body: JSON.stringify({
            source_landmark_id: sourceId,
            destination_landmark_id: destinationId,
          }),
        },
        'Combat connection removed',
      )}
    />
  );
}
