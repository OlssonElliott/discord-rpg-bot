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
  item_type: 'weapon' | 'armor' | 'clothing' | 'container' | 'consumable' | 'readable' | 'misc';
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

export type RoomData = {
  id: string;
  area_id: string;
  name: string;
  description: string;
  position: { x: number; y: number };
  counts: { players: number; enemies: number; items: number; containers: number };
  players: { id: number; name: string }[];
  enemies: { id: string; name: string; description?: string }[];
  npcs: { id: string; name: string; description?: string }[];
  containers: { id: string; name: string; description?: string }[];
  loose_items: { id: string; name: string; description?: string; quantity: number }[];
};

export type ConnectionData = {
  connection_id: string | null;
  source_room_id: string;
  exit_name: string;
  destination_room_id: string;
  return_exit_name: string | null;
  bidirectional: boolean;
  hidden: boolean;
};

export type AreaGraphData = {
  area: { id: string; name: string; description: string };
  nodes: RoomData[];
  connections: ConnectionData[];
};

const API_ROOT = process.env.NEXT_PUBLIC_RPG_API_URL || 'http://localhost:8765/api';

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

export function identifier(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'location';
  return `${slug}_${crypto.randomUUID().slice(0, 6)}`;
}
