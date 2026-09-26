export type AreaSummary = {
  id: string;
  name: string;
  description: string;
  room_count: number;
};

export type CharacterStatus = 'active' | 'downed' | 'stable' | 'recovering' | 'dead';

export type EquipmentSlotValue = 'main_hand' | 'off_hand' | 'clothing' | 'armor' | 'container';

export type CharacterSummary = {
  id: number;
  discord_user_id: number;
  name: string;
  current_room_id: string | null;
  current_room_name: string | null;
  is_active: boolean;
  portrait_url: string | null;
  race: string | null;
  lineage: string | null;
  hp: number;
  max_hp: number;
  status: CharacterStatus;
};

export type CharacterAdminData = {
  kind: 'character';
  source_id: string;
  id: number;
  discord_user_id: number;
  name: string;
  description: string;
  portrait_url: string | null;
  hp: number;
  max_hp: number;
  status: CharacterStatus;
  failed_death_saves: number;
  death_save_dc: number | null;
  stance: 'steady' | 'bad_stance' | 'prone';
  race: string | null;
  lineage: string | null;
  age: string | null;
  gender: string | null;
  current_room_id: string | null;
  current_room_name: string | null;
  is_active: boolean;
  attributes: Record<string, number>;
  skills: Record<string, number>;
  inventory: {
    id: string;
    template_id: string;
    name: string;
    description: string;
    quantity: number;
    durability: number | null;
    equipped_slot: EquipmentSlotValue | null;
  }[];
  equipment: {
    slot: EquipmentSlotValue;
    id: string;
    template_id: string;
    name: string;
    description: string;
  }[];
  wallet: {
    copper: number;
    silver: number;
    gold: number;
  };
  enemy: null;
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
  cover: 'none' | 'half' | 'full';
  x: number | null;
  y: number | null;
};

export type CombatEffectData = {
  id: string;
  name: string;
  effect_type: string;
  blocks_movement: boolean;
  movement_cost_modifier: number;
  remaining_rounds: number | null;
};

export type CombatRouteEffectData = CombatEffectData;

export type CombatRouteData = {
  source_landmark_id: string;
  destination_landmark_id: string;
  distance: 'close' | 'far' | 'distant';
  movement_cost: number;
  terrain: 'normal' | 'difficult';
  base_blocked: boolean;
  blocked: boolean;
  automatic: boolean;
  effects: CombatEffectData[];
};

export type CombatantData = {
  kind: 'character' | 'enemy';
  source_id: string;
  name: string;
  landmark_id: string;
  relation: 'at' | 'behind';
  initiative_roll: number;
  initiative_score: number;
  acted_this_round: boolean;
  movement_budget: number;
  movement_remaining: number;
  route_source_landmark_id: string | null;
  route_destination_landmark_id: string | null;
  route_progress: number;
  route_cost: number;
  is_between_landmarks: boolean;
  standard_action_spent: boolean;
  defending: boolean;
  usable_items: {
    id: string;
    template_id: string;
    name: string;
    quantity: number;
    affected_stat: string;
    affected_amount: number;
  }[];
  hp: number | null;
  max_hp: number | null;
  character_status: 'active' | 'downed' | 'stable' | 'recovering' | 'dead' | null;
  failed_death_saves: number | null;
  death_save_dc: number | null;
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
  failed_death_saves: number | null;
  death_save_dc: number | null;
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

export type CombatAttackResultData = {
  attacker_kind: 'character' | 'enemy';
  attacker_source_id: string;
  attacker_name: string;
  target_kind: 'character' | 'enemy';
  target_source_id: string;
  target_name: string;
  weapon_name: string;
  attack_attribute: string;
  attack_roll: number;
  attack_modifier: number;
  attack_total: number;
  defense_dc: number;
  hit: boolean;
  critical: boolean;
  damage_rolls: {
    die: number;
    damage_type: string;
    roll: number;
  }[];
  raw_damage: number;
  reduction: number;
  reduction_type: string;
  final_damage: number;
  target_hp: number;
  target_max_hp: number;
  target_defeated: boolean;
};

export type CombatEnemyAttackResultData = {
  attacker_source_id: string;
  attacker_name: string;
  target_source_id: string;
  target_name: string;
  attack_profile: string;
  attack_dc: number;
  defense_method: string;
  defense_attribute: string;
  defense_roll: number;
  defense_modifier: number;
  defense_total: number;
  defended: boolean;
  critical_defense: boolean;
  damage_expression: string;
  damage_rolls: number[];
  raw_damage: number;
  armor_reduction: number;
  final_damage: number;
  target_hp: number;
  target_max_hp: number;
  target_down: boolean;
  target_status: 'active' | 'downed' | 'stable' | 'recovering' | 'dead';
  target_dead: boolean;
};

export type CombatStateData = {
  scene: CombatSceneData | null;
  attack_result?: CombatAttackResultData;
  enemy_attack_result?: CombatEnemyAttackResultData;
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

export async function uploadCharacterPortrait<T>(characterId: number, file: File): Promise<T> {
  const response = await fetch(`${API_ROOT}/characters/${characterId}/portrait`, {
    method: 'POST',
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-File-Name': encodeURIComponent(file.name),
    },
    body: file,
  });
  const payload = await response.json() as T & { error?: string };
  if (!response.ok) {
    throw new Error(payload.error || `Portrait upload failed (${response.status}).`);
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
