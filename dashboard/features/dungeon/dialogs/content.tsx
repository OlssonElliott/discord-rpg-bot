'use client';

import {
  api,
  identifier,
  type CatalogItem,
  type EnemyTemplateData,
  type RoomData,
} from '@/lib/api';
import { ContainerEditorDialog, ContainerPlacementDialog } from './containers';
import { EnemyPlacementDialog } from './enemies';
import { ContentDialog } from './items';
import { RoomFeatureDialog } from './room-features';
import type {
  ContainerTemplateData,
  ContentKind,
  PlacedContainer,
  RoomFeatureTemplateData,
} from '../types';

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

type DungeonContentDialogsProps = {
  contentKind: ContentKind | null;
  catalogItems: CatalogItem[];
  room: RoomData | null;
  enemyPlacementOpen: boolean;
  enemyTemplates: EnemyTemplateData[];
  roomFeatureOpen: boolean;
  editingRoomFeature: RoomFeature | null;
  roomFeatureTemplates: RoomFeatureTemplateData[];
  containerPlacementOpen: boolean;
  containerTemplates: ContainerTemplateData[];
  selectedContainer: PlacedContainer | null;
  onContentKindChange: (kind: ContentKind | null) => void;
  onEnemyPlacementOpenChange: (open: boolean) => void;
  onRoomFeatureOpenChange: (open: boolean) => void;
  onEditingRoomFeatureChange: (feature: RoomFeature | null) => void;
  onContainerPlacementOpenChange: (open: boolean) => void;
  onEditingContainerIdChange: (id: string | null) => void;
  mutate: Mutate;
};

export function DungeonContentDialogs({
  contentKind,
  catalogItems,
  room,
  enemyPlacementOpen,
  enemyTemplates,
  roomFeatureOpen,
  editingRoomFeature,
  roomFeatureTemplates,
  containerPlacementOpen,
  containerTemplates,
  selectedContainer,
  onContentKindChange,
  onEnemyPlacementOpenChange,
  onRoomFeatureOpenChange,
  onEditingRoomFeatureChange,
  onContainerPlacementOpenChange,
  onEditingContainerIdChange,
  mutate,
}: DungeonContentDialogsProps) {
  return (
    <>
      <ContentDialog
        kind={contentKind}
        catalogItems={catalogItems}
        onOpenChange={(open) => {
          if (!open) onContentKindChange(null);
        }}
        onCreate={async (name, quantity) => {
          if (!room || !contentKind) return;
          const path = contentKind === 'item' ? 'items' : 'entities';
          const payload = contentKind === 'item'
            ? { item_id: name, quantity }
            : { id: identifier(name), name, kind: contentKind };
          const ok = await mutate(
            () => api(`/rooms/${room.id}/${path}`, {
              method: 'POST',
              body: JSON.stringify(payload),
            }),
            `${name} added`,
          );
          if (ok) onContentKindChange(null);
        }}
      />

      <EnemyPlacementDialog
        open={enemyPlacementOpen}
        templates={enemyTemplates}
        onOpenChange={onEnemyPlacementOpenChange}
        onPlace={async (templateId, quantity) => {
          if (!room) return false;
          const template = enemyTemplates.find((item) => item.id === templateId);
          const ok = await mutate(async () => {
            for (let index = 0; index < quantity; index += 1) {
              await api(`/rooms/${room.id}/enemies`, {
                method: 'POST',
                body: JSON.stringify({ template_id: templateId }),
              });
            }
          }, `${template?.name || 'Enemy'} ×${quantity} added`);
          if (ok) onEnemyPlacementOpenChange(false);
          return ok;
        }}
      />

      <RoomFeatureDialog
        open={roomFeatureOpen}
        feature={editingRoomFeature}
        templates={roomFeatureTemplates}
        onOpenChange={(open) => {
          onRoomFeatureOpenChange(open);
          if (!open) onEditingRoomFeatureChange(null);
        }}
        onSave={async (record) => {
          if (!room) return false;
          const editing = editingRoomFeature;
          const ok = await mutate(
            () => api(
              editing
                ? `/room-features/${editing.id}`
                : `/rooms/${room.id}/features`,
              {
                method: editing ? 'PATCH' : 'POST',
                body: JSON.stringify(
                  editing
                    ? record
                    : {
                      ...record,
                      id: identifier(`${room.id} ${record.name}`),
                    },
                ),
              },
            ),
            `${record.name} ${editing ? 'updated' : 'added'}`,
          );
          if (ok) {
            onRoomFeatureOpenChange(false);
            onEditingRoomFeatureChange(null);
          }
          return ok;
        }}
        onDelete={editingRoomFeature ? async () => {
          const ok = await mutate(
            () => api(`/room-features/${editingRoomFeature.id}`, { method: 'DELETE' }),
            `${editingRoomFeature.name} removed`,
          );
          if (ok) {
            onRoomFeatureOpenChange(false);
            onEditingRoomFeatureChange(null);
          }
          return ok;
        } : undefined}
      />

      <ContainerPlacementDialog
        open={containerPlacementOpen}
        templates={containerTemplates}
        onOpenChange={onContainerPlacementOpenChange}
        onPlace={async (templateId) => {
          if (!room) return false;
          const template = containerTemplates.find((item) => item.id === templateId);
          const ok = await mutate(
            () => api(`/rooms/${room.id}/containers`, {
              method: 'POST',
              body: JSON.stringify({ template_id: templateId }),
            }),
            `${template?.name || 'Container'} added`,
          );
          if (ok) onContainerPlacementOpenChange(false);
          return ok;
        }}
        onCreateAndPlace={async (draft) => {
          if (!room) return false;
          const ok = await mutate(async () => {
            const created = await api<ContainerTemplateData>('/container-templates', {
              method: 'POST',
              body: JSON.stringify({
                id: identifier(draft.name),
                name: draft.name,
                type: draft.type,
                description: draft.description,
                default_has_lock: draft.lockState !== 'none',
                default_is_locked: draft.lockState === 'locked',
                default_is_broken: draft.lockState === 'broken',
                default_unlock_difficulty: draft.lockState === 'locked' ? draft.unlockDifficulty : null,
                default_hidden: draft.hidden,
                default_discovery_difficulty: draft.hidden ? draft.discoveryDifficulty : null,
              }),
            });
            await api(`/rooms/${room.id}/containers`, {
              method: 'POST',
              body: JSON.stringify({ template_id: created.id }),
            });
          }, `${draft.name} created and added`);
          if (ok) onContainerPlacementOpenChange(false);
          return ok;
        }}
      />

      <ContainerEditorDialog
        key={selectedContainer?.id ?? 'container-editor'}
        container={selectedContainer}
        catalogItems={catalogItems}
        onOpenChange={(open) => {
          if (!open) onEditingContainerIdChange(null);
        }}
        onSave={async (record) => {
          if (!selectedContainer) return false;
          return mutate(
            () => api(`/containers/${selectedContainer.id}`, {
              method: 'PATCH',
              body: JSON.stringify(record),
            }),
            `${record.name} updated`,
          );
        }}
        onAddItem={async (itemId, quantity) => {
          if (!selectedContainer) return false;
          return mutate(
            () => api(`/containers/${selectedContainer.id}/items`, {
              method: 'POST',
              body: JSON.stringify({ item_id: itemId, quantity }),
            }),
            'Container contents updated',
          );
        }}
        onSetQuantity={async (itemId, quantity) => {
          if (!selectedContainer) return false;
          return mutate(
            () => api(`/containers/${selectedContainer.id}/items/${itemId}`, {
              method: 'PUT',
              body: JSON.stringify({ quantity }),
            }),
            'Container contents updated',
          );
        }}
        onRemoveItem={async (itemId) => {
          if (!selectedContainer) return false;
          return mutate(
            () => api(`/containers/${selectedContainer.id}/items/${itemId}`, {
              method: 'DELETE',
            }),
            'Item removed from container',
          );
        }}
      />
    </>
  );
}
