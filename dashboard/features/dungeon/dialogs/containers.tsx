'use client';

import { useState } from 'react';
import { Plus, Save, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import type { CatalogItem } from '@/lib/api';
import { CONTAINER_TYPES } from '../constants';
import type {
  ContainerTemplateData,
  ContainerTemplateDraft,
  ContainerTypeValue,
  DoorLockState,
  PlacedContainer,
} from '../types';

export function ContainerPlacementDialog({
  open,
  templates,
  onOpenChange,
  onPlace,
  onCreateAndPlace,
}: {
  open: boolean;
  templates: ContainerTemplateData[];
  onOpenChange: (open: boolean) => void;
  onPlace: (templateId: string) => Promise<boolean>;
  onCreateAndPlace: (draft: ContainerTemplateDraft) => Promise<boolean>;
}) {
  const [templateId, setTemplateId] = useState('');
  const [search, setSearch] = useState('');
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [containerType, setContainerType] = useState<ContainerTypeValue>('wooden_chest');
  const [description, setDescription] = useState('');
  const [lockState, setLockState] = useState<DoorLockState>('none');
  const [unlockDifficulty, setUnlockDifficulty] = useState(10);
  const [hidden, setHidden] = useState(false);
  const [discoveryDifficulty, setDiscoveryDifficulty] = useState(10);
  const filtered = templates.filter((template) => {
    const query = search.trim().toLocaleLowerCase();
    return !query
      || template.name.toLocaleLowerCase().includes(query)
      || template.type.toLocaleLowerCase().includes(query);
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add container</DialogTitle>
          <DialogDescription>
            Place a reusable container definition, or create a new definition and place it here.
          </DialogDescription>
        </DialogHeader>
        {!creating ? (
          <>
            <label className="dialog-label" htmlFor="container-search">Search library</label>
            <Input id="container-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Chest, corpse, shelf…" />
            <label className="dialog-label" htmlFor="container-template">Container</label>
            <NativeSelect id="container-template" value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
              <NativeSelectOption value="">Choose a container…</NativeSelectOption>
              {filtered.map((template) => (
                <NativeSelectOption key={template.id} value={template.id}>
                  {template.name} · {CONTAINER_TYPES.find((item) => item.value === template.type)?.label ?? template.type}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Button type="button" variant="outline" onClick={() => setCreating(true)}>
              <Plus /> New container definition
            </Button>
            <DialogFooter>
              <Button
                disabled={!templateId}
                onClick={async () => {
                  if (await onPlace(templateId)) onOpenChange(false);
                }}
              >
                Add container
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <label className="dialog-label" htmlFor="new-container-name">Name</label>
            <Input id="new-container-name" value={name} onChange={(event) => setName(event.target.value)} />
            <label className="dialog-label" htmlFor="new-container-type">Type</label>
            <NativeSelect id="new-container-type" value={containerType} onChange={(event) => setContainerType(event.target.value as ContainerTypeValue)}>
              {CONTAINER_TYPES.map((item) => <NativeSelectOption key={item.value} value={item.value}>{item.label}</NativeSelectOption>)}
            </NativeSelect>
            <label className="dialog-label" htmlFor="new-container-description">Description</label>
            <Textarea id="new-container-description" value={description} onChange={(event) => setDescription(event.target.value)} />
            <label className="dialog-label" htmlFor="new-container-lock">Default lock</label>
            <NativeSelect id="new-container-lock" value={lockState} onChange={(event) => setLockState(event.target.value as DoorLockState)}>
              <NativeSelectOption value="none">No lock</NativeSelectOption>
              <NativeSelectOption value="unlocked">Unlocked</NativeSelectOption>
              <NativeSelectOption value="locked">Locked</NativeSelectOption>
              <NativeSelectOption value="broken">Broken</NativeSelectOption>
            </NativeSelect>
            {lockState === 'locked' && (
              <>
                <label className="dialog-label" htmlFor="new-container-unlock-difficulty">Unlock difficulty (1–30)</label>
                <Input id="new-container-unlock-difficulty" type="number" min={1} max={30} value={unlockDifficulty} onChange={(event) => setUnlockDifficulty(Number(event.target.value))} />
              </>
            )}
            <label className="dialog-label" htmlFor="new-container-hidden">Default visibility</label>
            <NativeSelect id="new-container-hidden" value={hidden ? 'hidden' : 'visible'} onChange={(event) => setHidden(event.target.value === 'hidden')}>
              <NativeSelectOption value="visible">Visible</NativeSelectOption>
              <NativeSelectOption value="hidden">Hidden</NativeSelectOption>
            </NativeSelect>
            {hidden && (
              <>
                <label className="dialog-label" htmlFor="new-container-discovery-difficulty">Discovery DC (1–30)</label>
                <Input id="new-container-discovery-difficulty" type="number" min={1} max={30} value={discoveryDifficulty} onChange={(event) => setDiscoveryDifficulty(Number(event.target.value))} />
              </>
            )}
            <Button type="button" variant="outline" onClick={() => setCreating(false)}>Back to library</Button>
            <DialogFooter>
              <Button
                disabled={
                  !name.trim()
                  || (lockState === 'locked' && (!Number.isInteger(unlockDifficulty) || unlockDifficulty < 1 || unlockDifficulty > 30))
                  || (hidden && (!Number.isInteger(discoveryDifficulty) || discoveryDifficulty < 1 || discoveryDifficulty > 30))
                }
                onClick={async () => {
                  if (await onCreateAndPlace({
                    name,
                    type: containerType,
                    description,
                    lockState,
                    unlockDifficulty,
                    hidden,
                    discoveryDifficulty,
                  })) onOpenChange(false);
                }}
              >
                Create and place
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function ContainerEditorDialog({
  container,
  catalogItems,
  onOpenChange,
  onSave,
  onAddItem,
  onSetQuantity,
  onRemoveItem,
}: {
  container: PlacedContainer | null;
  catalogItems: CatalogItem[];
  onOpenChange: (open: boolean) => void;
  onSave: (record: {
    name: string;
    description: string;
    has_lock: boolean;
    is_locked: boolean;
    is_broken: boolean;
    unlock_difficulty: number | null;
    hidden: boolean;
    discovery_difficulty: number | null;
    is_open: boolean;
    searched: boolean;
  }) => Promise<boolean>;
  onAddItem: (itemId: string, quantity: number) => Promise<boolean>;
  onSetQuantity: (itemId: string, quantity: number) => Promise<boolean>;
  onRemoveItem: (itemId: string) => Promise<boolean>;
}) {
  const [name, setName] = useState(container?.name ?? '');
  const [description, setDescription] = useState(container?.description ?? '');
  const [lockState, setLockState] = useState<DoorLockState>(
    container?.has_lock
      ? container.is_broken
        ? 'broken'
        : container.is_locked
          ? 'locked'
          : 'unlocked'
      : 'none',
  );
  const [unlockDifficulty, setUnlockDifficulty] = useState(container?.unlock_difficulty ?? 10);
  const [hidden, setHidden] = useState(container?.hidden ?? false);
  const [discoveryDifficulty, setDiscoveryDifficulty] = useState(container?.discovery_difficulty ?? 10);
  const [isOpen, setIsOpen] = useState(container?.is_open ?? false);
  const [searched, setSearched] = useState(container?.searched ?? false);
  const [itemId, setItemId] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [quantities, setQuantities] = useState<Record<string, number>>({});

  return (
    <Dialog open={Boolean(container)} onOpenChange={onOpenChange}>
      <DialogContent>
        {container && (
          <>
            <DialogHeader>
              <DialogTitle>Edit {container.name}</DialogTitle>
              <DialogDescription>
                {CONTAINER_TYPES.find((item) => item.value === container.type)?.label ?? container.type}
                {' · '}
                template {container.template_id}
              </DialogDescription>
            </DialogHeader>
            <label className="dialog-label" htmlFor="container-editor-name">Name</label>
            <Input id="container-editor-name" value={name} onChange={(event) => setName(event.target.value)} />
            <label className="dialog-label" htmlFor="container-editor-description">Description</label>
            <Textarea id="container-editor-description" value={description} onChange={(event) => setDescription(event.target.value)} />

            <h3>Contents</h3>
            {container.contents.map((item) => (
              <div key={item.id}>
                <strong>{item.name}</strong>
                <Input
                  aria-label={`${item.name} quantity`}
                  type="number"
                  min={1}
                  value={quantities[item.id] ?? item.quantity}
                  onChange={(event) => setQuantities((current) => ({
                    ...current,
                    [item.id]: Number(event.target.value),
                  }))}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={(quantities[item.id] ?? item.quantity) < 1}
                  onClick={() => void onSetQuantity(item.id, quantities[item.id] ?? item.quantity)}
                >
                  Save quantity
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => void onRemoveItem(item.id)}>
                  <Trash2 /> Remove
                </Button>
              </div>
            ))}
            {!container.contents.length && <p className="muted-row">Container is empty.</p>}
            <label className="dialog-label" htmlFor="container-editor-item">Add item</label>
            <NativeSelect id="container-editor-item" value={itemId} onChange={(event) => setItemId(event.target.value)}>
              <NativeSelectOption value="">Choose an item…</NativeSelectOption>
              {catalogItems.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.name} · {item.item_type}</NativeSelectOption>)}
            </NativeSelect>
            <label className="dialog-label" htmlFor="container-editor-item-quantity">Quantity</label>
            <Input id="container-editor-item-quantity" type="number" min={1} value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!itemId || quantity < 1}
              onClick={async () => {
                if (await onAddItem(itemId, quantity)) {
                  setItemId('');
                  setQuantity(1);
                }
              }}
            >
              <Plus /> Add item
            </Button>

            <h3>Lock</h3>
            <NativeSelect
              value={lockState}
              onChange={(event) => {
                const next = event.target.value as DoorLockState;
                setLockState(next);
                if (next === 'locked') setIsOpen(false);
              }}
            >
              <NativeSelectOption value="none">No lock</NativeSelectOption>
              <NativeSelectOption value="unlocked">Unlocked</NativeSelectOption>
              <NativeSelectOption value="locked">Locked</NativeSelectOption>
              <NativeSelectOption value="broken">Broken</NativeSelectOption>
            </NativeSelect>
            {lockState === 'locked' && (
              <Input type="number" min={1} max={30} value={unlockDifficulty} onChange={(event) => setUnlockDifficulty(Number(event.target.value))} />
            )}

            <h3>Hidden / discovery</h3>
            <NativeSelect value={hidden ? 'hidden' : 'visible'} onChange={(event) => setHidden(event.target.value === 'hidden')}>
              <NativeSelectOption value="visible">Visible</NativeSelectOption>
              <NativeSelectOption value="hidden">Hidden</NativeSelectOption>
            </NativeSelect>
            {hidden && (
              <Input type="number" min={1} max={30} value={discoveryDifficulty} onChange={(event) => setDiscoveryDifficulty(Number(event.target.value))} />
            )}
            <label>
              <input type="checkbox" checked={isOpen} disabled={lockState === 'locked'} onChange={(event) => setIsOpen(event.target.checked)} />
              Opened
            </label>
            <label>
              <input type="checkbox" checked={searched} onChange={(event) => setSearched(event.target.checked)} />
              Searched
            </label>

            <DialogFooter>
              <Button
                disabled={
                  !name.trim()
                  || (lockState === 'locked' && (!Number.isInteger(unlockDifficulty) || unlockDifficulty < 1 || unlockDifficulty > 30))
                  || (hidden && (!Number.isInteger(discoveryDifficulty) || discoveryDifficulty < 1 || discoveryDifficulty > 30))
                }
                onClick={async () => {
                  const saved = await onSave({
                    name,
                    description,
                    has_lock: lockState !== 'none',
                    is_locked: lockState === 'locked',
                    is_broken: lockState === 'broken',
                    unlock_difficulty: lockState === 'locked' ? unlockDifficulty : null,
                    hidden,
                    discovery_difficulty: hidden ? discoveryDifficulty : null,
                    is_open: isOpen && lockState !== 'locked',
                    searched,
                  });
                  if (saved) onOpenChange(false);
                }}
              >
                <Save /> Save container
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
