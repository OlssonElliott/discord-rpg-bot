export type AreaSummary = {
  id: string;
  name: string;
  description: string;
  room_count: number;
};

export type CharacterSummary = {
  id: number;
  discord_user_id: number;
  name: string;
  current_room_id: string | null;
  is_active: boolean;
};

export type CatalogItem = {
  id: string;
  item_type: 'weapon' | 'armor' | 'clothing' | 'container' | 'consumable' | 'readable' | 'tool' | 'misc';
  name: string;
  rarity: string;
  value: number;
  description: string;
  weight: number;
  slot_cost: number;
  stackable: boolean;
  content: string | null;
  grip?: string;
  durability?: number;
  damage?: number;
  damage_type?: string;
  protection?: number;
  dodge_penalty?: number;
  strength_requirement?: number | null;
  capacity?: number;
  can_equip?: boolean;
  affected_amount?: number;
};

export type EnemyTemplateData = {
  id: string;
  name: string;
  description: string;
  race: string;
  difficulty_level: number;
  strength: number;
  dexterity: number;
  arcana: number;
  vitality: number;
  insight: number;
  personality: number;
  max_hp: number;
  armor: number;
  magical_resistance: number;
  attack_dc: number;
  defense_dc: number;
  damage: string;
  attack_profile: string;
  special_ability: string | null;
  typical_behaviour: string;
  main_hand_item_id: string | null;
  off_hand_item_id: string | null;
  armor_item_id: string | null;
};

export type PlacedEnemy = {
  id: string;
  room_id: string;
  template_id: string | null;
  template_name: string | null;
  name: string;
  description: string;
  current_hp: number | null;
  max_hp: number | null;
  status: 'active' | 'dead' | 'fled';
};

export type RoomData = {
  id: string;
  area_id: string;
  name: string;
  description: string;
  room_image_url: string | null;
  position: { x: number; y: number };
  counts: { players: number; enemies: number; items: number; containers: number; room_features?: number };
  players: { id: number; name: string }[];
  enemies: PlacedEnemy[];
  npcs: { id: string; name: string; description?: string }[];
  containers: { id: string; name: string; description?: string }[];
  loose_items: { id: string; name: string; description?: string; quantity: number }[];
  room_features?: {
    id: string;
    room_id: string;
    name: string;
    description: string;
    feature_type: string;
  }[];
};

export type CombatLandmarkData = {
  id: string;
  name: string;
  description: string;
  source_feature_id: string | null;
  source_connection_id: string | null;
  feature_type: string | null;
  synthetic: boolean;
  x: number | null;
  y: number | null;
};

export type CombatRouteData = {
  source_landmark_id: string;
  destination_landmark_id: string;
  distance: 'close' | 'far' | 'distant';
  obstacle: string | null;
  blocked: boolean;
};

export type CombatantData = {
  kind: 'character' | 'enemy';
  source_id: string;
  name: string;
  landmark_id: string;
  relation: 'at' | 'beside' | 'behind' | 'on' | 'inside';
  initiative_roll: number;
  initiative_score: number;
  acted_this_round: boolean;
  is_current_turn: boolean;
};

export type CombatLogEntryData = {
  id: number;
  round_number: number;
  event_type: string;
  message: string;
  created_at: string;
  actor_kind: 'character' | 'enemy' | null;
  actor_source_id: string | null;
  actor_name: string | null;
};

export type CombatSceneData = {
  id: number;
  guild_id: number;
  room_id: string;
  room_name: string;
  area_id: string | null;
  status: 'active' | 'ended';
  round_number: number;
  current_turn_kind: 'character' | 'enemy' | null;
  current_turn_source_id: string | null;
  landmarks: CombatLandmarkData[];
  routes: CombatRouteData[];
  combatants: CombatantData[];
  log_entries: CombatLogEntryData[];
};

export type CombatInspectItemData = {
  id: string;
  template_id: string;
  name: string;
  description: string;
  quantity?: number;
  durability?: number | null;
  equipped_slot?: string | null;
  slot?: string;
};

export type CombatantInspectData = {
  kind: 'character' | 'enemy';
  source_id: string;
  name: string;
  description: string;
  hp: number | null;
  max_hp: number | null;
  status: string;
  stance: string | null;
  race: string | null;
  lineage: string | null;
  age: string | null;
  gender: string | null;
  attributes: Record<string, number>;
  skills: Record<string, number>;
  inventory: CombatInspectItemData[];
  equipment: CombatInspectItemData[];
  wallet: {
    copper: number;
    silver: number;
    gold: number;
  } | null;
  enemy: {
    template_id: string;
    template_name: string;
    difficulty_level: number;
    armor: number;
    magical_resistance: number;
    attack_dc: number;
    defense_dc: number;
    damage: string;
    attack_profile: string;
    special_ability: string | null;
    typical_behaviour: string;
  } | null;
};

export type CombatStateData = {
  scene: CombatSceneData | null;
};

export type ConnectionData = {
  connection_id: string | null;
  source_room_id: string;
  exit_name: string;
  destination_room_id: string;
  return_exit_name: string | null;
  bidirectional: boolean;
  hidden: boolean;
  connection_type: string;
  has_lock: boolean;
  is_locked: boolean;
  is_broken: boolean;
  is_open: boolean;
  unlock_difficulty: number | null;
  has_trap: boolean;
  trap_state: 'armed' | 'disarmed' | 'triggered' | null;
  trap_detection_difficulty: number | null;
  trap_disarm_difficulty: number | null;
  trap_damage_type: string | null;
  trap_damage: number | null;
};

export type AreaGraphData = {
  area: { id: string; name: string; description: string };
  nodes: RoomData[];
  connections: ConnectionData[];
};

const API_ROOT = process.env.NEXT_PUBLIC_RPG_API_URL || 'http://localhost:8765/api';

export function apiAssetUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_ROOT.replace(/\/api\/?$/, '')}${path}`;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set('Content-Type', 'application/json');
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers,
  });
  const payload = await response.json() as T & { error?: string };
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status}).`);
  }
  return payload;
}

export async function uploadRoomImage<T>(roomId: string, file: File): Promise<T> {
  const response = await fetch(`${API_ROOT}/rooms/${encodeURIComponent(roomId)}/image`, {
    method: 'POST',
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-File-Name': encodeURIComponent(file.name),
    },
    body: file,
  });
  const payload = await response.json() as T & { error?: string };
  if (!response.ok) {
    throw new Error(payload.error || `Image upload failed (${response.status}).`);
  }
  return payload;
}

export function identifier(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'location';
  return `${slug}_${crypto.randomUUID().slice(0, 6)}`;
}
