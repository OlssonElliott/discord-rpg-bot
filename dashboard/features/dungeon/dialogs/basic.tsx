'use client';

import { useEffect, useState } from 'react';
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
import { Textarea } from '@/components/ui/textarea';

export function AreaDialog({ open, onOpenChange, onCreate }: { open: boolean; onOpenChange: (open: boolean) => void; onCreate: (name: string, description: string) => Promise<void> }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  return <EditorDialog open={open} onOpenChange={onOpenChange} title="Create area" description="Start a separate location graph." name={name} setName={setName} details={description} setDetails={setDescription} action="Create area" onSubmit={() => onCreate(name, description)} />;
}

export function RoomDialog({ open, onOpenChange, onCreate }: { open: boolean; onOpenChange: (open: boolean) => void; onCreate: (name: string, description: string) => Promise<void> }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  return <EditorDialog open={open} onOpenChange={onOpenChange} title="Add location" description="Coordinates are assigned automatically; drag the node afterward." name={name} setName={setName} details={description} setDetails={setDescription} action="Add location" onSubmit={() => onCreate(name, description)} />;
}

export function CombatLandmarkDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (name: string, description: string) => Promise<boolean>;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    if (!open) {
      setName('');
      setDescription('');
    }
  }, [open]);

  return (
    <EditorDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add landmark"
      description="Add a combat-only landmark. It starts unconnected in a free part of the room."
      name={name}
      setName={setName}
      details={description}
      setDetails={setDescription}
      action="Add landmark"
      onSubmit={async () => {
        if (await onCreate(name, description)) {
          onOpenChange(false);
        }
      }}
    />
  );
}

function EditorDialog({ open, onOpenChange, title, description, name, setName, details, setDetails, action, onSubmit }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description: string; name: string; setName: (value: string) => void; details: string; setDetails: (value: string) => void; action: string; onSubmit: () => Promise<void> }) {
  const prefix = title.toLowerCase().replaceAll(' ', '-');
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{description}</DialogDescription></DialogHeader>
        <label className="dialog-label" htmlFor={`${prefix}-name`}>Name</label>
        <Input id={`${prefix}-name`} value={name} onChange={(event) => setName(event.target.value)} />
        <label className="dialog-label" htmlFor={`${prefix}-description`}>Description</label>
        <Textarea id={`${prefix}-description`} value={details} onChange={(event) => setDetails(event.target.value)} />
        <DialogFooter><Button disabled={!name.trim()} onClick={() => void onSubmit()}>{action}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
