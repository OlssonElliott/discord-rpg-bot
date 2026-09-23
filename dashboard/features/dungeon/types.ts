import type { EnemyTemplateData } from '@/lib/api';

export type ContentKind = 'enemy' | 'item' | 'container';
export type MapConnectionType = 'door' | 'hallway';
export type DoorLockState = 'none' | 'unlocked' | 'locked' | 'broken';
export type DoorState = 'closed' | 'open';
export type TrapDamageType =
  | 'physical'
  | 'fire'
  | 'cold'
  | 'lightning'
  | 'poison'
  | 'acid';
export type TrapState = 'armed' | 'disarmed' | 'triggered';

export type ContainerTypeValue =
  | 'wooden_chest'
  | 'reinforced_chest'
  | 'barrel'
  | 'crate'
  | 'shelf'
  | 'bookshelf'
  | 'corpse'
  | 'skeleton'
  | 'backpack'
  | 'hidden_compartment'
  | 'loose_floorboard'
  | 'other';

export type ContainerTemplateData = {
  id: string;
  name: string;
  type: ContainerTypeValue;
  description: string;
  default_has_lock: boolean;
  default_is_locked: boolean;
  default_is_broken: boolean;
  default_unlock_difficulty: number | null;
  default_hidden: boolean;
  default_discovery_difficulty: number | null;
};

export type RoomFeatureTemplateData = {
  id: string;
  name: string;
  description: string;
  feature_type: string;
};

export type EnemyTemplateDraft = Omit<EnemyTemplateData, 'id'>;

export type ContainerContentItem = {
  id: string;
  name: string;
  description: string | null;
  quantity: number;
};

export type PlacedContainer = {
  id: string;
  room_id: string;
  template_id: string;
  name: string;
  type: ContainerTypeValue;
  description: string;
  has_lock: boolean;
  is_locked: boolean;
  is_broken: boolean;
  unlock_difficulty: number | null;
  hidden: boolean;
  discovery_difficulty: number | null;
  is_open: boolean;
  searched: boolean;
  item_count: number;
  contents: ContainerContentItem[];
};

export type ContainerTemplateDraft = {
  name: string;
  type: ContainerTypeValue;
  description: string;
  lockState: DoorLockState;
  unlockDifficulty: number;
  hidden: boolean;
  discoveryDifficulty: number;
};
