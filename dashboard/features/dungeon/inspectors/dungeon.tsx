'use client';

import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  api,
  uploadRoomImage,
  type CharacterSummary,
  type ConnectionData,
  type RoomData,
} from '@/lib/api';
import { ConnectionInspector } from './connection';
import { RoomInspector } from './room';
import { edgeId } from '../editor/graph';
import type { ContentKind } from '../types';

type RoomFeature = {
  id: string;
  room_id: string;
  name: string;
  description: string;
  feature_type: string;
};

type Mutate = (
  action: () => Promise<unknown>,
  message: string,
) => Promise<boolean>;

type DungeonInspectorProps = {
  open: boolean;
  room: RoomData | null;
  connection: ConnectionData | null;
  rooms: RoomData[];
  connections: ConnectionData[];
  characters: CharacterSummary[];
  mutate: Mutate;
  onClose: () => void;
  onAddContent: (kind: ContentKind) => void;
  onEditContainer: (id: string) => void;
  onAddRoomFeature: () => void;
  onEditRoomFeature: (feature: RoomFeature) => void;
  onStartCombat: (roomId: string) => Promise<boolean>;
  onDeleteRoom: () => void;
  onSelectConnection: (connection: ConnectionData) => void;
};

export function DungeonInspector({
  open,
  room,
  connection,
  rooms,
  connections,
  characters,
  mutate,
  onClose,
  onAddContent,
  onEditContainer,
  onAddRoomFeature,
  onEditRoomFeature,
  onStartCombat,
  onDeleteRoom,
  onSelectConnection,
}: DungeonInspectorProps) {
  if (!open) return null;

  return (
    <aside className="inspector">
      <div className="inspector__toolbar">
        <span>Inspector</span>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onClose}
          title="Close inspector"
          aria-label="Close inspector"
        >
          <X />
        </Button>
      </div>
      {room ? (
        <RoomInspector
          key={`${room.id}:${room.name}:${room.description}:${room.room_image_url || ''}`}
          room={room}
          connections={connections}
          rooms={rooms}
          characters={characters}
          onSave={(name, description) => mutate(
            () => api(`/rooms/${room.id}`, {
              method: 'PATCH',
              body: JSON.stringify({ name, description }),
            }),
            'Location saved',
          )}
          onUploadImage={(file) => mutate(
            () => uploadRoomImage(room.id, file),
            'Room image saved',
          )}
          onRemoveImage={() => mutate(
            () => api(`/rooms/${room.id}/image`, { method: 'DELETE' }),
            'Room image removed',
          )}
          onAddContent={onAddContent}
          onEditContainer={onEditContainer}
          onAddRoomFeature={onAddRoomFeature}
          onEditRoomFeature={onEditRoomFeature}
          onRemoveContent={(kind, id) => mutate(
            () => api(
              kind === 'item'
                ? `/rooms/${room.id}/items/${id}`
                : kind === 'container'
                  ? `/containers/${id}`
                  : `/rooms/${room.id}/entities/${id}`,
              { method: 'DELETE' },
            ),
            `${kind === 'item' ? 'Item' : kind === 'container' ? 'Container' : 'Enemy'} removed`,
          )}
          onPlaceCharacter={(characterId) => mutate(
            () => api(`/characters/${characterId}/room`, {
              method: 'PATCH',
              body: JSON.stringify({ room_id: room.id }),
            }),
            'Character moved',
          )}
          onStartCombat={() => onStartCombat(room.id)}
          onDelete={onDeleteRoom}
          onSelectConnection={onSelectConnection}
        />
      ) : connection ? (
        <ConnectionInspector
          key={`${edgeId(connection)}:${connection.connection_type}:${connection.is_open}:${connection.has_lock}:${connection.is_locked}:${connection.is_broken}:${connection.unlock_difficulty ?? ''}:${connection.has_trap}:${connection.trap_state ?? ''}:${connection.trap_detection_difficulty ?? ''}:${connection.trap_disarm_difficulty ?? ''}:${connection.trap_damage_type ?? ''}:${connection.trap_damage ?? ''}:${connection.bidirectional}:${connection.return_exit_name || ''}`}
          connection={connection}
          rooms={rooms}
          onSave={(
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
          ) => mutate(
            () => api('/connections', {
              method: 'PATCH',
              body: JSON.stringify({
                source_room_id: connection.source_room_id,
                exit_name: connection.exit_name,
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
            'Connection updated',
          )}
          onRemove={() => {
            void mutate(
              () => api('/connections', {
                method: 'DELETE',
                body: JSON.stringify({
                  source_room_id: connection.source_room_id,
                  exit_name: connection.exit_name,
                }),
              }),
              'Connection removed',
            );
          }}
        />
      ) : (
        <div className="inspector-empty">
          <p>Select a location or connection to edit it.</p>
        </div>
      )}
    </aside>
  );
}
