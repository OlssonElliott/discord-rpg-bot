'use client';

import { useState } from 'react';
import type { Connection } from '@xyflow/react';
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
import { TRAP_DAMAGE_TYPES } from '../constants';
import { exitNameForHandle } from '../editor/graph';
import type {
  DoorLockState,
  DoorState,
  MapConnectionType,
  TrapDamageType,
  TrapState,
} from '../types';

export function ConnectionDialog({ connection, onOpenChange, onCreate }: { connection: Connection | null; onOpenChange: (open: boolean) => void; onCreate: (name: string, connectionType: MapConnectionType, doorState: DoorState, lockState: DoorLockState, unlockDifficulty: number, hasTrap: boolean, trapState: TrapState, trapDetectionDifficulty: number, trapDisarmDifficulty: number, trapDamageType: TrapDamageType, trapDamage: number, bidirectional: boolean, returnName: string) => Promise<void> }) {
  const [name, setName] = useState(() => exitNameForHandle(connection?.sourceHandle));
  const [bidirectional, setBidirectional] = useState(true);
  const [connectionType, setConnectionType] = useState<MapConnectionType>('hallway');
  const [doorState, setDoorState] = useState<DoorState>('closed');
  const [lockState, setLockState] = useState<DoorLockState>('none');
  const [unlockDifficulty, setUnlockDifficulty] = useState(10);
  const [hasTrap, setHasTrap] = useState(false);
  const [trapState, setTrapState] = useState<TrapState>('armed');
  const [trapDetectionDifficulty, setTrapDetectionDifficulty] = useState(10);
  const [trapDisarmDifficulty, setTrapDisarmDifficulty] = useState(10);
  const [trapDamageType, setTrapDamageType] = useState<TrapDamageType>('physical');
  const [trapDamage, setTrapDamage] = useState(1);
  const [returnName, setReturnName] = useState(() => exitNameForHandle(connection?.targetHandle));
  return (
    <Dialog open={Boolean(connection)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Create passage</DialogTitle><DialogDescription>Passages work in both directions by default. Choose one-way only when the return path should be blocked.</DialogDescription></DialogHeader>
        <label className="dialog-label" htmlFor="connection-name">Exit name</label>
        <Input id="connection-name" value={name} onChange={(event) => { const next = event.target.value; setReturnName((current) => current === name ? next : current); setName(next); }} />
        <label className="dialog-label" htmlFor="new-connection-type">Map marker</label>
        <NativeSelect id="new-connection-type" value={connectionType} onChange={(event) => setConnectionType(event.target.value as MapConnectionType)}>
          <NativeSelectOption value="door">Door</NativeSelectOption>
          <NativeSelectOption value="hallway">Hallway</NativeSelectOption>
        </NativeSelect>
        {connectionType === 'door' && <>
          <label className="dialog-label" htmlFor="new-connection-door-state">Door state</label>
          <NativeSelect id="new-connection-door-state" value={doorState} onChange={(event) => { const next = event.target.value as DoorState; setDoorState(next); if (next === 'open' && lockState === 'locked') setLockState('unlocked'); }}>
            <NativeSelectOption value="closed">Closed</NativeSelectOption>
            <NativeSelectOption value="open">Open</NativeSelectOption>
          </NativeSelect>
          <label className="dialog-label" htmlFor="new-connection-lock-state">Lock state</label>
          <NativeSelect id="new-connection-lock-state" value={lockState} onChange={(event) => { const next = event.target.value as DoorLockState; setLockState(next); if (next === 'locked') setDoorState('closed'); }}>
            <NativeSelectOption value="none">No lock</NativeSelectOption>
            <NativeSelectOption value="unlocked">Unlocked</NativeSelectOption>
            <NativeSelectOption value="locked">Locked</NativeSelectOption>
            <NativeSelectOption value="broken">Broken</NativeSelectOption>
          </NativeSelect>
          {lockState === 'locked' && <><label className="dialog-label" htmlFor="new-connection-unlock-difficulty">Unlock difficulty (1–30)</label><Input id="new-connection-unlock-difficulty" type="number" min={1} max={30} step={1} value={unlockDifficulty} onChange={(event) => setUnlockDifficulty(Number(event.target.value))} /></>}
        </>}
        <label className="dialog-label" htmlFor="new-connection-trap-state">Trap</label>
        <NativeSelect id="new-connection-trap-state" value={hasTrap ? 'trapped' : 'none'} onChange={(event) => { const trapped = event.target.value === 'trapped'; setHasTrap(trapped); if (trapped) setTrapState('armed'); }}>
          <NativeSelectOption value="none">No trap</NativeSelectOption>
          <NativeSelectOption value="trapped">Trapped</NativeSelectOption>
        </NativeSelect>
        {hasTrap && <>
          <label className="dialog-label" htmlFor="new-connection-trap-status">Trap state</label>
          <NativeSelect id="new-connection-trap-status" value={trapState} onChange={(event) => setTrapState(event.target.value as TrapState)}>
            <NativeSelectOption value="armed">Armed</NativeSelectOption>
            <NativeSelectOption value="disarmed">Disarmed</NativeSelectOption>
            <NativeSelectOption value="triggered">Triggered</NativeSelectOption>
          </NativeSelect>
          <label className="dialog-label" htmlFor="new-connection-trap-difficulty">Insight detection difficulty (1–30)</label>
          <Input id="new-connection-trap-difficulty" type="number" min={1} max={30} step={1} value={trapDetectionDifficulty} onChange={(event) => setTrapDetectionDifficulty(Number(event.target.value))} />
          <label className="dialog-label" htmlFor="new-connection-trap-disarm-difficulty">Disarm difficulty (1–30)</label>
          <Input id="new-connection-trap-disarm-difficulty" type="number" min={1} max={30} step={1} value={trapDisarmDifficulty} onChange={(event) => setTrapDisarmDifficulty(Number(event.target.value))} />
          <label className="dialog-label" htmlFor="new-connection-trap-damage-type">Damage type</label>
          <NativeSelect id="new-connection-trap-damage-type" value={trapDamageType} onChange={(event) => setTrapDamageType(event.target.value as TrapDamageType)}>
            {TRAP_DAMAGE_TYPES.map((item) => <NativeSelectOption key={item.value} value={item.value}>{item.label}</NativeSelectOption>)}
          </NativeSelect>
          <label className="dialog-label" htmlFor="new-connection-trap-damage">Damage</label>
          <Input id="new-connection-trap-damage" type="number" min={1} step={1} value={trapDamage} onChange={(event) => setTrapDamage(Number(event.target.value))} />
        </>}
        <label className="dialog-label" htmlFor="new-connection-direction">Direction</label>
        <NativeSelect id="new-connection-direction" value={bidirectional ? 'two-way' : 'one-way'} onChange={(event) => setBidirectional(event.target.value === 'two-way')}>
          <NativeSelectOption value="two-way">Two-way passage</NativeSelectOption>
          <NativeSelectOption value="one-way">One-way passage</NativeSelectOption>
        </NativeSelect>
        {bidirectional && <><label className="dialog-label" htmlFor="new-return-exit-name">Return exit name</label><Input id="new-return-exit-name" value={returnName} onChange={(event) => setReturnName(event.target.value)} /></>}
        <DialogFooter><Button disabled={!name.trim() || (bidirectional && !returnName.trim()) || (connectionType === 'door' && lockState === 'locked' && (!Number.isInteger(unlockDifficulty) || unlockDifficulty < 1 || unlockDifficulty > 30)) || (hasTrap && ((!Number.isInteger(trapDetectionDifficulty) || trapDetectionDifficulty < 1 || trapDetectionDifficulty > 30) || (!Number.isInteger(trapDisarmDifficulty) || trapDisarmDifficulty < 1 || trapDisarmDifficulty > 30) || (!Number.isInteger(trapDamage) || trapDamage < 1)))} onClick={() => void onCreate(name, connectionType, doorState, lockState, unlockDifficulty, hasTrap, trapState, trapDetectionDifficulty, trapDisarmDifficulty, trapDamageType, trapDamage, bidirectional, returnName)}>Create connection</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
