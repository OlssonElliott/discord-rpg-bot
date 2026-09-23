import type { ContainerTypeValue, TrapDamageType } from './types';

export const CONTAINER_TYPES: { value: ContainerTypeValue; label: string }[] = [
  { value: 'wooden_chest', label: 'Wooden Chest' },
  { value: 'reinforced_chest', label: 'Reinforced Chest' },
  { value: 'barrel', label: 'Barrel' },
  { value: 'crate', label: 'Crate' },
  { value: 'shelf', label: 'Shelf' },
  { value: 'bookshelf', label: 'Bookshelf' },
  { value: 'corpse', label: 'Corpse' },
  { value: 'skeleton', label: 'Skeleton' },
  { value: 'backpack', label: 'Backpack' },
  { value: 'hidden_compartment', label: 'Hidden Compartment' },
  { value: 'loose_floorboard', label: 'Loose Floorboard' },
  { value: 'other', label: 'Other' },
];

export const TRAP_DAMAGE_TYPES: { value: TrapDamageType; label: string }[] = [
  { value: 'physical', label: 'Physical' },
  { value: 'fire', label: 'Fire' },
  { value: 'cold', label: 'Cold' },
  { value: 'lightning', label: 'Lightning' },
  { value: 'poison', label: 'Poison' },
  { value: 'acid', label: 'Acid' },
];

export function normalizedTrapDamageType(value: string | null): TrapDamageType {
  return TRAP_DAMAGE_TYPES.some((item) => item.value === value)
    ? value as TrapDamageType
    : 'physical';
}
