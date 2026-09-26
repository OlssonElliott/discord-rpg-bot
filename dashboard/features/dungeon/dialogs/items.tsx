'use client';

import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
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
import type { ContentKind } from '../types';

export function ContentDialog({ kind, catalogItems, onOpenChange, onCreate }: { kind: ContentKind | null; catalogItems: CatalogItem[]; onOpenChange: (open: boolean) => void; onCreate: (name: string, quantity: number) => Promise<void> }) {
  const [name, setName] = useState('');
  const [quantity, setQuantity] = useState(1);
  return (
    <Dialog open={Boolean(kind)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Add {kind}</DialogTitle><DialogDescription>{kind === 'item' ? 'Choose an existing item from the shared library.' : 'This creates a persisted world object in the selected location.'}</DialogDescription></DialogHeader>
        <label className="dialog-label" htmlFor="content-name">{kind === 'item' ? 'Item' : 'Name'}</label>
        {kind === 'item' ? (
          <NativeSelect id="content-name" value={name} onChange={(event) => setName(event.target.value)}>
            <NativeSelectOption value="">Choose an item…</NativeSelectOption>
            {catalogItems.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.name} · {item.item_type}</NativeSelectOption>)}
          </NativeSelect>
        ) : <Input id="content-name" value={name} onChange={(event) => setName(event.target.value)} />}
        {kind === 'item' && <><label className="dialog-label" htmlFor="content-quantity">Quantity</label><Input id="content-quantity" type="number" min={1} value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} /></>}
        <DialogFooter><Button disabled={!name.trim() || quantity < 1} onClick={() => void onCreate(name, quantity)}>Add {kind}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type ItemDraft = {
  name: string;
  item_type: CatalogItem['item_type'];
  description: string;
  rarity: string;
  value: number;
  weight: number;
  slot_cost: number;
  grip?: string;
  durability?: number;
  range?: number;
  damage?: number;
  damage_type?: string;
  protection?: number;
  dodge_penalty?: number;
  strength_requirement?: number;
  capacity?: number;
  can_equip?: boolean;
  affected_amount?: number;
  content?: string;
};

export function ItemLibraryDialog({ open, items, onOpenChange, onSave }: { open: boolean; items: CatalogItem[]; onOpenChange: (open: boolean) => void; onSave: (record: ItemDraft, itemId?: string) => Promise<void> }) {
  const [editingId, setEditingId] = useState<string | undefined>();
  const [name, setName] = useState('');
  const [itemType, setItemType] = useState<CatalogItem['item_type']>('misc');
  const [description, setDescription] = useState('');
  const [rarity, setRarity] = useState('Common');
  const [value, setValue] = useState(0);
  const [weight, setWeight] = useState(0);
  const [slotCost, setSlotCost] = useState(1);
  const [power, setPower] = useState(1);
  const [damageType, setDamageType] = useState('physical');
  const [weaponRange, setWeaponRange] = useState(0);
  const [grip, setGrip] = useState('one_handed');
  const [canEquip, setCanEquip] = useState(false);
  const [readableContent, setReadableContent] = useState('');
  const [stackable, setStackable] = useState(false);
  const [itemTypeFilter, setItemTypeFilter] = useState<CatalogItem['item_type'] | 'all'>('all');

  const editingItem = items.find((item) => item.id === editingId);
  const filteredItems = itemTypeFilter === 'all' ? items : items.filter((item) => item.item_type === itemTypeFilter);
  useEffect(() => {
    setStackable(editingItem?.stackable ?? false);
  }, [editingItem]);

  const record: ItemDraft = { name, item_type: itemType, description, rarity, value, weight, slot_cost: slotCost };
  Object.assign(record, { stackable });
  if (itemType === 'weapon') Object.assign(record, { grip, durability: editingItem?.durability ?? 40, range: weaponRange, damage: power, damage_type: damageType });
  if (itemType === 'armor') Object.assign(record, { protection: power, dodge_penalty: editingItem?.dodge_penalty ?? 0, strength_requirement: editingItem?.strength_requirement ?? 0 });
  if (itemType === 'container') Object.assign(record, { capacity: power, can_equip: canEquip });
  if (itemType === 'consumable') Object.assign(record, { affected_amount: power });
  if (itemType === 'readable') Object.assign(record, { content: readableContent });

  const editItem = (item?: CatalogItem) => {
    setEditingId(item?.id);
    setName(item?.name ?? '');
    setItemType(item?.item_type ?? 'misc');
    setDescription(item?.description ?? '');
    setRarity(item?.rarity ?? 'Common');
    setValue(item?.value ?? 0);
    setWeight(item?.weight ?? 0);
    setSlotCost(item?.slot_cost ?? (item?.item_type === 'readable' && item.weight === 0 ? 0 : 1));
    setReadableContent(item?.content ?? '');
    setGrip(item?.grip ?? 'one_handed');
    setDamageType(item?.damage_type ?? 'physical');
    setWeaponRange(item?.range ?? 0);
    setCanEquip(item?.can_equip ?? false);
    setPower(
      item?.damage
      ?? item?.protection
      ?? item?.capacity
      ?? item?.affected_amount
      ?? 1
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Item library</DialogTitle><DialogDescription>Create and edit item types here. Rooms and containers can only use entries from this shared library.</DialogDescription></DialogHeader>
        <div className="catalog-heading"><div className="catalog-count">{items.length} item types available</div><button type="button" onClick={() => editItem()}>New item</button></div>
        <label className="dialog-label" htmlFor="item-library-type-filter">Filter by type
          <NativeSelect id="item-library-type-filter" value={itemTypeFilter} onChange={(event) => setItemTypeFilter(event.target.value as CatalogItem['item_type'] | 'all')}>
            <NativeSelectOption value="all">All types</NativeSelectOption>
            <NativeSelectOption value="misc">Misc</NativeSelectOption>
            <NativeSelectOption value="tool">Tool</NativeSelectOption>
            <NativeSelectOption value="weapon">Weapon</NativeSelectOption>
            <NativeSelectOption value="armor">Armor</NativeSelectOption>
            <NativeSelectOption value="clothing">Clothing</NativeSelectOption>
            <NativeSelectOption value="container">Container</NativeSelectOption>
            <NativeSelectOption value="consumable">Consumable</NativeSelectOption>
            <NativeSelectOption value="readable">Readable</NativeSelectOption>
          </NativeSelect>
        </label>
        <div className="catalog-list" aria-label="Existing item types">
          {filteredItems.map((item) => (
            <button type="button" className={editingId === item.id ? 'selected' : ''} key={item.id} onClick={() => editItem(item)}><span>{item.name}</span><Badge variant="outline">{item.item_type}</Badge></button>
          ))}
        </div>
        <div className="catalog-grid">
          <label className="dialog-label" htmlFor="item-name">Name<Input id="item-name" value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label className="dialog-label" htmlFor="item-type">Type<NativeSelect id="item-type" value={itemType} disabled={Boolean(editingId)} onChange={(event) => { const nextType = event.target.value as CatalogItem['item_type']; setItemType(nextType); setStackable(nextType === 'consumable' || nextType === 'tool'); if (nextType === 'readable' && weight === 0) setSlotCost(0); }}><NativeSelectOption value="misc">Misc</NativeSelectOption><NativeSelectOption value="tool">Tool</NativeSelectOption><NativeSelectOption value="weapon">Weapon</NativeSelectOption><NativeSelectOption value="armor">Armor</NativeSelectOption><NativeSelectOption value="clothing">Clothing</NativeSelectOption><NativeSelectOption value="container">Container</NativeSelectOption><NativeSelectOption value="consumable">Consumable</NativeSelectOption><NativeSelectOption value="readable">Readable</NativeSelectOption></NativeSelect></label>
          <label className="dialog-label" htmlFor="item-stackable">Stackable<input id="item-stackable" type="checkbox" checked={stackable} onChange={(event) => setStackable(event.target.checked)} /></label>
          <label className="dialog-label" htmlFor="item-rarity">Rarity<Input id="item-rarity" value={rarity} onChange={(event) => setRarity(event.target.value)} /></label>
          <label className="dialog-label" htmlFor="item-value">Value<Input id="item-value" type="number" min={0} value={value} onChange={(event) => setValue(Number(event.target.value))} /></label>
          <label className="dialog-label" htmlFor="item-weight">Weight<Input id="item-weight" type="number" min={0} value={weight} onChange={(event) => setWeight(Number(event.target.value))} /></label>
          <label className="dialog-label" htmlFor="item-slots">Storage slots<Input id="item-slots" type="number" min={0} value={slotCost} onChange={(event) => setSlotCost(Number(event.target.value))} /></label>
          {!['misc', 'tool', 'clothing', 'readable'].includes(itemType) && <label className="dialog-label" htmlFor="item-power">{itemType === 'weapon' ? 'Damage' : itemType === 'armor' ? 'Protection' : itemType === 'container' ? 'Capacity' : 'Healing'}<Input id="item-power" type="number" min={1} value={power} onChange={(event) => setPower(Number(event.target.value))} /></label>}
          {itemType === 'weapon' && <><label className="dialog-label" htmlFor="item-damage-type">Damage type<Input id="item-damage-type" value={damageType} onChange={(event) => setDamageType(event.target.value)} /></label><label className="dialog-label" htmlFor="item-range">Range<Input id="item-range" type="number" min={0} value={weaponRange} onChange={(event) => setWeaponRange(Number(event.target.value))} /></label><label className="dialog-label" htmlFor="item-grip">Grip<NativeSelect id="item-grip" value={grip} onChange={(event) => setGrip(event.target.value)}><NativeSelectOption value="one_handed">One handed</NativeSelectOption><NativeSelectOption value="two_handed">Two handed</NativeSelectOption></NativeSelect></label></>}
          {itemType === 'container' && <label className="catalog-check"><input type="checkbox" checked={canEquip} onChange={(event) => setCanEquip(event.target.checked)} /> Can be equipped</label>}
        </div>
        <label className="dialog-label" htmlFor="item-description">Description</label>
        <Textarea id="item-description" value={description} onChange={(event) => setDescription(event.target.value)} />
        {itemType === 'readable' && <label className="dialog-label" htmlFor="item-readable-content">Readable content<Textarea className="readable-content-input" id="item-readable-content" value={readableContent} onChange={(event) => setReadableContent(event.target.value)} /></label>}
        <DialogFooter><Button disabled={!name.trim() || !rarity.trim() || value < 0 || weight < 0 || slotCost < 0 || power < 1 || weaponRange < 0} onClick={() => void onSave(record, editingId)}>{editingId ? 'Save item type' : 'Create item type'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
