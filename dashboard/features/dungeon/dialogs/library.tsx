'use client';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  api,
  identifier,
  type CatalogItem,
  type EnemyTemplateData,
  type RoomData,
} from '@/lib/api';
import { EnemyLibraryDialog } from './enemies';
import { ItemLibraryDialog } from './items';
import { FeatureLibraryDialog } from './room-features';
import type { RoomFeatureTemplateData } from '../types';

type Mutate = (
  action: () => Promise<unknown>,
  message: string,
) => Promise<boolean>;

type DungeonLibraryDialogsProps = {
  itemLibraryOpen: boolean;
  enemyLibraryOpen: boolean;
  featureLibraryOpen: boolean;
  deleteOpen: boolean;
  catalogItems: CatalogItem[];
  enemyTemplates: EnemyTemplateData[];
  roomFeatureTemplates: RoomFeatureTemplateData[];
  selectedRoom: RoomData | null;
  onItemLibraryOpenChange: (open: boolean) => void;
  onEnemyLibraryOpenChange: (open: boolean) => void;
  onFeatureLibraryOpenChange: (open: boolean) => void;
  onDeleteOpenChange: (open: boolean) => void;
  mutate: Mutate;
};

export function DungeonLibraryDialogs({
  itemLibraryOpen,
  enemyLibraryOpen,
  featureLibraryOpen,
  deleteOpen,
  catalogItems,
  enemyTemplates,
  roomFeatureTemplates,
  selectedRoom,
  onItemLibraryOpenChange,
  onEnemyLibraryOpenChange,
  onFeatureLibraryOpenChange,
  onDeleteOpenChange,
  mutate,
}: DungeonLibraryDialogsProps) {
  return (
    <>
      <ItemLibraryDialog
        open={itemLibraryOpen}
        items={catalogItems}
        onOpenChange={onItemLibraryOpenChange}
        onSave={async (record, itemId) => {
          const ok = await mutate(
            () => api(itemId ? `/items/${itemId}` : '/items', {
              method: itemId ? 'PUT' : 'POST',
              body: JSON.stringify(
                itemId ? record : { ...record, id: identifier(record.name) },
              ),
            }),
            `${record.name} ${itemId ? 'updated' : 'created'}`,
          );
          if (ok) onItemLibraryOpenChange(false);
        }}
      />

      <EnemyLibraryDialog
        open={enemyLibraryOpen}
        templates={enemyTemplates}
        catalogItems={catalogItems}
        onOpenChange={onEnemyLibraryOpenChange}
        onSave={(editingId, record) => mutate(
          () => api(
            editingId ? `/enemy-templates/${editingId}` : '/enemy-templates',
            {
              method: editingId ? 'PUT' : 'POST',
              body: JSON.stringify(
                editingId ? record : { ...record, id: identifier(record.name) },
              ),
            },
          ),
          `${record.name} ${editingId ? 'updated' : 'created'}`,
        )}
        onDelete={(template) => mutate(
          () => api(`/enemy-templates/${template.id}`, { method: 'DELETE' }),
          `${template.name} removed`,
        )}
      />

      <FeatureLibraryDialog
        open={featureLibraryOpen}
        templates={roomFeatureTemplates}
        onOpenChange={onFeatureLibraryOpenChange}
        onSave={(editingId, record) => mutate(
          () => api(
            editingId
              ? `/room-feature-templates/${editingId}`
              : '/room-feature-templates',
            {
              method: editingId ? 'PATCH' : 'POST',
              body: JSON.stringify(
                editingId ? record : { ...record, id: identifier(record.name) },
              ),
            },
          ),
          `${record.name} ${editingId ? 'updated' : 'created'}`,
        )}
        onDelete={(template) => mutate(
          () => api(`/room-feature-templates/${template.id}`, { method: 'DELETE' }),
          `${template.name} removed`,
        )}
      />

      <AlertDialog open={deleteOpen} onOpenChange={onDeleteOpenChange}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {selectedRoom?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Attached connections will be removed. Occupied locations must be emptied first.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (selectedRoom) {
                  void mutate(
                    () => api(`/rooms/${selectedRoom.id}`, { method: 'DELETE' }),
                    'Location deleted',
                  );
                }
              }}
            >
              Delete location
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
