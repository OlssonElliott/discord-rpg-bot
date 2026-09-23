'use client';

import type { Connection } from '@xyflow/react';
import { api, identifier } from '@/lib/api';
import { ConnectionDialog } from './connection';
import { AreaDialog, CombatLandmarkDialog, RoomDialog } from './basic';

type Mutate = (
  action: () => Promise<unknown>,
  message: string,
) => Promise<boolean>;

type UpdateCombat = (
  path: string,
  init: RequestInit,
  message: string,
) => Promise<boolean>;

type DungeonCreationDialogsProps = {
  addAreaOpen: boolean;
  addRoomOpen: boolean;
  addCombatLandmarkOpen: boolean;
  connection: Connection | null;
  areaId: string;
  roomCount: number;
  onAddAreaOpenChange: (open: boolean) => void;
  onAddRoomOpenChange: (open: boolean) => void;
  onAddCombatLandmarkOpenChange: (open: boolean) => void;
  onConnectionChange: (connection: Connection | null) => void;
  loadAreas: (preferredArea?: string) => Promise<void>;
  mutate: Mutate;
  updateCombat: UpdateCombat;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
};

export function DungeonCreationDialogs({
  addAreaOpen,
  addRoomOpen,
  addCombatLandmarkOpen,
  connection,
  areaId,
  roomCount,
  onAddAreaOpenChange,
  onAddRoomOpenChange,
  onAddCombatLandmarkOpenChange,
  onConnectionChange,
  loadAreas,
  mutate,
  updateCombat,
  onNotice,
  onError,
}: DungeonCreationDialogsProps) {
  return (
    <>
      <AreaDialog
        open={addAreaOpen}
        onOpenChange={onAddAreaOpenChange}
        onCreate={async (name, description) => {
          try {
            const id = identifier(name);
            const created = await api<{ id: string }>('/areas', {
              method: 'POST',
              body: JSON.stringify({ id, name, description }),
            });
            await loadAreas(created.id);
            onAddAreaOpenChange(false);
            onNotice('Area created');
          } catch (requestError) {
            onError(
              requestError instanceof Error
                ? requestError.message
                : 'Could not create the area.',
            );
          }
        }}
      />

      <RoomDialog
        open={addRoomOpen}
        onOpenChange={onAddRoomOpenChange}
        onCreate={async (name, description) => {
          const offset = roomCount * 36;
          const ok = await mutate(
            () => api(`/areas/${areaId}/rooms`, {
              method: 'POST',
              body: JSON.stringify({
                id: identifier(name),
                name,
                description,
                x: 180 + offset,
                y: 140 + offset,
              }),
            }),
            'Location created',
          );
          if (ok) onAddRoomOpenChange(false);
        }}
      />

      <CombatLandmarkDialog
        open={addCombatLandmarkOpen}
        onOpenChange={onAddCombatLandmarkOpenChange}
        onCreate={(name, description) => updateCombat(
          '/combat/landmarks',
          {
            method: 'POST',
            body: JSON.stringify({ name, description }),
          },
          'Landmark added',
        )}
      />

      <ConnectionDialog
        key={`${connection?.source || ''}:${connection?.sourceHandle || ''}:${connection?.target || ''}:${connection?.targetHandle || ''}`}
        connection={connection}
        onOpenChange={(open) => {
          if (!open) onConnectionChange(null);
        }}
        onCreate={async (
          exitName,
          connectionType,
          doorState,
          lockState,
          unlockDifficulty,
          hasTrap,
          trapState,
          trapDetectionDifficulty,
          trapDisarmDifficulty,
          trapDamageType,
          trapDamage,
          bidirectional,
          returnExitName,
        ) => {
          if (!connection?.source || !connection.target) return;
          const ok = await mutate(
            () => api('/connections', {
              method: 'POST',
              body: JSON.stringify({
                source_room_id: connection.source,
                destination_room_id: connection.target,
                exit_name: exitName,
                connection_type: connectionType,
                is_open: connectionType === 'door' && doorState === 'open',
                has_lock: connectionType === 'door' && lockState !== 'none',
                is_locked: connectionType === 'door' && lockState === 'locked',
                is_broken: connectionType === 'door' && lockState === 'broken',
                unlock_difficulty: connectionType === 'door' && lockState === 'locked'
                  ? unlockDifficulty
                  : null,
                has_trap: hasTrap,
                trap_state: hasTrap ? trapState : null,
                trap_detection_difficulty: hasTrap ? trapDetectionDifficulty : null,
                trap_disarm_difficulty: hasTrap ? trapDisarmDifficulty : null,
                trap_damage_type: hasTrap ? trapDamageType : null,
                trap_damage: hasTrap ? trapDamage : null,
                bidirectional,
                return_exit_name: bidirectional ? returnExitName : null,
              }),
            }),
            'Connection created',
          );
          if (ok) onConnectionChange(null);
        }}
      />
    </>
  );
}
