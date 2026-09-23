'use client';

import { useState } from 'react';
import { Save, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type { ConnectionData, RoomData } from '@/lib/api';
import {
  TRAP_DAMAGE_TYPES,
  normalizedTrapDamageType,
} from '../constants';
import type {
  DoorLockState,
  DoorState,
  MapConnectionType,
  TrapDamageType,
  TrapState,
} from '../types';

export function ConnectionInspector({ connection, rooms, onSave, onRemove }: { connection: ConnectionData; rooms: RoomData[]; onSave: (connectionType: MapConnectionType, doorState: DoorState, lockState: DoorLockState, unlockDifficulty: number, hasTrap: boolean, trapState: TrapState, trapDetectionDifficulty: number, trapDisarmDifficulty: number, trapDamageType: TrapDamageType, trapDamage: number, bidirectional: boolean, returnExitName: string) => Promise<boolean>; onRemove: () => void }) {
  const roomName = (id: string) => rooms.find((room) => room.id === id)?.name || id;
  const [bidirectional, setBidirectional] = useState(connection.bidirectional);
  const [returnExitName, setReturnExitName] = useState(connection.return_exit_name || connection.exit_name);
  const [connectionType, setConnectionType] = useState<MapConnectionType>(connection.connection_type === 'door' ? 'door' : 'hallway');
  const [doorState, setDoorState] = useState<DoorState>(connection.is_open ? 'open' : 'closed');
  const [lockState, setLockState] = useState<DoorLockState>(connection.has_lock ? (connection.is_broken ? 'broken' : connection.is_locked ? 'locked' : 'unlocked') : 'none');
  const [unlockDifficulty, setUnlockDifficulty] = useState(connection.unlock_difficulty ?? 10);
  const [hasTrap, setHasTrap] = useState(connection.has_trap);
  const [trapState, setTrapState] = useState<TrapState>(connection.trap_state ?? 'armed');
  const [trapDetectionDifficulty, setTrapDetectionDifficulty] = useState(connection.trap_detection_difficulty ?? 10);
  const [trapDisarmDifficulty, setTrapDisarmDifficulty] = useState(connection.trap_disarm_difficulty ?? 10);
  const [trapDamageType, setTrapDamageType] = useState<TrapDamageType>(normalizedTrapDamageType(connection.trap_damage_type));
  const [trapDamage, setTrapDamage] = useState(connection.trap_damage ?? 1);
  return (
    <>
      <div className="inspector__topline"><span>Selected connection</span><Badge>{connectionType === 'door' ? 'Door' : 'Hallway'}</Badge></div>
      <h2>{connection.exit_name}</h2>
      <div className="route-card"><strong>{roomName(connection.source_room_id)}</strong><span>{connection.bidirectional ? '↔' : '→'}</span><strong>{roomName(connection.destination_room_id)}</strong></div>
      <label className="dialog-label" htmlFor="connection-type">Map marker</label>
      <NativeSelect id="connection-type" value={connectionType} onChange={(event) => setConnectionType(event.target.value as MapConnectionType)}>
        <NativeSelectOption value="door">Door</NativeSelectOption>
        <NativeSelectOption value="hallway">Hallway</NativeSelectOption>
      </NativeSelect>
      {connectionType === 'door' && <>
        <label className="dialog-label" htmlFor="connection-door-state">Door state</label>
        <NativeSelect id="connection-door-state" value={doorState} onChange={(event) => { const next = event.target.value as DoorState; setDoorState(next); if (next === 'open' && lockState === 'locked') setLockState('unlocked'); }}>
          <NativeSelectOption value="closed">Closed</NativeSelectOption>
          <NativeSelectOption value="open">Open</NativeSelectOption>
        </NativeSelect>
        <label className="dialog-label" htmlFor="connection-lock-state">Lock state</label>
        <NativeSelect id="connection-lock-state" value={lockState} onChange={(event) => { const next = event.target.value as DoorLockState; setLockState(next); if (next === 'locked') setDoorState('closed'); }}>
          <NativeSelectOption value="none">No lock</NativeSelectOption>
          <NativeSelectOption value="unlocked">Unlocked</NativeSelectOption>
          <NativeSelectOption value="locked">Locked</NativeSelectOption>
          <NativeSelectOption value="broken">Broken</NativeSelectOption>
        </NativeSelect>
        {lockState === 'locked' && <><label className="dialog-label" htmlFor="connection-unlock-difficulty">Unlock difficulty (1–30)</label><Input id="connection-unlock-difficulty" type="number" min={1} max={30} step={1} value={unlockDifficulty} onChange={(event) => setUnlockDifficulty(Number(event.target.value))} /></>}
      </>}
      <label className="dialog-label" htmlFor="connection-trap-state">Trap</label>
      <NativeSelect id="connection-trap-state" value={hasTrap ? 'trapped' : 'none'} onChange={(event) => { const trapped = event.target.value === 'trapped'; setHasTrap(trapped); if (trapped) setTrapState('armed'); }}>
        <NativeSelectOption value="none">No trap</NativeSelectOption>
        <NativeSelectOption value="trapped">Trapped</NativeSelectOption>
      </NativeSelect>
      {hasTrap && <>
        <label className="dialog-label" htmlFor="connection-trap-status">Trap state</label>
        <NativeSelect id="connection-trap-status" value={trapState} onChange={(event) => setTrapState(event.target.value as TrapState)}>
          <NativeSelectOption value="armed">Armed</NativeSelectOption>
          <NativeSelectOption value="disarmed">Disarmed</NativeSelectOption>
          <NativeSelectOption value="triggered">Triggered</NativeSelectOption>
        </NativeSelect>
        <label className="dialog-label" htmlFor="connection-trap-difficulty">Insight detection difficulty (1–30)</label>
        <Input id="connection-trap-difficulty" type="number" min={1} max={30} step={1} value={trapDetectionDifficulty} onChange={(event) => setTrapDetectionDifficulty(Number(event.target.value))} />
        <label className="dialog-label" htmlFor="connection-trap-disarm-difficulty">Disarm difficulty (1–30)</label>
        <Input id="connection-trap-disarm-difficulty" type="number" min={1} max={30} step={1} value={trapDisarmDifficulty} onChange={(event) => setTrapDisarmDifficulty(Number(event.target.value))} />
        <label className="dialog-label" htmlFor="connection-trap-damage-type">Damage type</label>
        <NativeSelect id="connection-trap-damage-type" value={trapDamageType} onChange={(event) => setTrapDamageType(event.target.value as TrapDamageType)}>
          {TRAP_DAMAGE_TYPES.map((item) => <NativeSelectOption key={item.value} value={item.value}>{item.label}</NativeSelectOption>)}
        </NativeSelect>
        <label className="dialog-label" htmlFor="connection-trap-damage">Damage</label>
        <Input id="connection-trap-damage" type="number" min={1} step={1} value={trapDamage} onChange={(event) => setTrapDamage(Number(event.target.value))} />
      </>}
      <label className="dialog-label" htmlFor="connection-direction">Direction</label>
      <NativeSelect id="connection-direction" value={bidirectional ? 'two-way' : 'one-way'} onChange={(event) => setBidirectional(event.target.value === 'two-way')}>
        <NativeSelectOption value="two-way">Two-way passage</NativeSelectOption>
        <NativeSelectOption value="one-way">One-way passage</NativeSelectOption>
      </NativeSelect>
      {bidirectional && <><label className="dialog-label" htmlFor="return-exit-name">Return exit name</label><Input id="return-exit-name" value={returnExitName} onChange={(event) => setReturnExitName(event.target.value)} /></>}
      <p className="inspector-note">Movement rules update immediately when this passage is saved.</p>
      <Button disabled={(bidirectional && !returnExitName.trim()) || (connectionType === 'door' && lockState === 'locked' && (!Number.isInteger(unlockDifficulty) || unlockDifficulty < 1 || unlockDifficulty > 30)) || (hasTrap && ((!Number.isInteger(trapDetectionDifficulty) || trapDetectionDifficulty < 1 || trapDetectionDifficulty > 30) || (!Number.isInteger(trapDisarmDifficulty) || trapDisarmDifficulty < 1 || trapDisarmDifficulty > 30) || (!Number.isInteger(trapDamage) || trapDamage < 1)))} onClick={() => void onSave(connectionType, doorState, lockState, unlockDifficulty, hasTrap, trapState, trapDetectionDifficulty, trapDisarmDifficulty, trapDamageType, trapDamage, bidirectional, returnExitName)}><Save /> Save connection</Button>
      <Button variant="destructive" onClick={onRemove}><Trash2 /> Remove connection</Button>
    </>
  );
}
