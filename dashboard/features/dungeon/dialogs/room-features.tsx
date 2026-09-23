'use client';

import { useEffect, useState } from 'react';
import { Save, Trash2 } from 'lucide-react';
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
import type { RoomFeatureTemplateData } from '../types';

export function RoomFeatureDialog({
  open,
  feature,
  templates,
  onOpenChange,
  onSave,
  onDelete,
}: {
  open: boolean;
  feature: {
    id: string;
    room_id: string;
    name: string;
    description: string;
    feature_type: string;
  } | null;
  templates: RoomFeatureTemplateData[];
  onOpenChange: (open: boolean) => void;
  onSave: (record: {
    name: string;
    description: string;
    feature_type: string;
  }) => Promise<boolean>;
  onDelete?: () => Promise<boolean>;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [featureType, setFeatureType] = useState('furniture');
  const [templateId, setTemplateId] = useState('');
  const availableTemplates = [
    ...DEFAULT_ROOM_FEATURE_TEMPLATES.filter(
      (preset) => !templates.some((template) => template.id === preset.id),
    ),
    ...templates,
  ];

  useEffect(() => {
    if (!open) return;
    setTemplateId('');
    setName(feature?.name ?? '');
    setDescription(feature?.description ?? '');
    setFeatureType(feature?.feature_type ?? 'furniture');
  }, [feature, open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{feature ? `Edit ${feature.name}` : 'Add Room Feature'}</DialogTitle>
          <DialogDescription>
            Room Features are persistent descriptive objects in this location.
          </DialogDescription>
        </DialogHeader>
        {!feature && availableTemplates.length > 0 && (
          <>
            <label className="dialog-label" htmlFor="room-feature-template">From feature library</label>
            <NativeSelect
              id="room-feature-template"
              value={templateId}
              onChange={(event) => {
                const nextId = event.target.value;
                setTemplateId(nextId);
                const template = availableTemplates.find((item) => item.id === nextId);
                if (!template) return;
                setName(template.name);
                setDescription(template.description);
                setFeatureType(template.feature_type);
              }}
            >
              <NativeSelectOption value="">Create from scratch…</NativeSelectOption>
              {availableTemplates.map((template) => (
                <NativeSelectOption key={template.id} value={template.id}>{template.name}</NativeSelectOption>
              ))}
            </NativeSelect>
          </>
        )}
        <label className="dialog-label" htmlFor="room-feature-name">Name</label>
        <Input id="room-feature-name" value={name} onChange={(event) => setName(event.target.value)} />
        <label className="dialog-label" htmlFor="room-feature-type">Type</label>
        <NativeSelect id="room-feature-type" value={featureType} onChange={(event) => setFeatureType(event.target.value)}>
          <NativeSelectOption value="furniture">furniture</NativeSelectOption>
          <NativeSelectOption value="decoration">decoration</NativeSelectOption>
          <NativeSelectOption value="structure">structure</NativeSelectOption>
          <NativeSelectOption value="environmental">environmental</NativeSelectOption>
          <NativeSelectOption value="other">other</NativeSelectOption>
        </NativeSelect>
        <label className="dialog-label" htmlFor="room-feature-description">Description</label>
        <Textarea id="room-feature-description" value={description} onChange={(event) => setDescription(event.target.value)} />
        <DialogFooter>
          {feature && onDelete && (
            <Button type="button" variant="outline" onClick={() => void onDelete()}>
              <Trash2 /> Delete
            </Button>
          )}
          <Button
            disabled={!name.trim()}
            onClick={() => void onSave({
              name,
              description,
              feature_type: featureType,
            })}
          >
            <Save /> {feature ? 'Save Room Feature' : 'Add Room Feature'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const DEFAULT_ROOM_FEATURE_TEMPLATES: RoomFeatureTemplateData[] = [
  {
    id: 'wooden_table',
    name: 'Wooden Table',
    feature_type: 'furniture',
    description: 'A sturdy wooden table with a worn, practical surface.',
  },
  {
    id: 'wooden_chair',
    name: 'Wooden Chair',
    feature_type: 'furniture',
    description: 'A plain wooden chair, scuffed from years of use.',
  },
  {
    id: 'simple_bed',
    name: 'Simple Bed',
    feature_type: 'furniture',
    description: 'A simple bed with a wooden frame and a thin mattress.',
  },
  {
    id: 'wooden_bench',
    name: 'Wooden Bench',
    feature_type: 'furniture',
    description: 'A long wooden bench suitable for halls, taverns, and waiting rooms.',
  },
  {
    id: 'bookshelf',
    name: 'Bookshelf',
    feature_type: 'furniture',
    description: 'A tall shelf built to hold books, ledgers, or small curios.',
  },
  {
    id: 'fireplace',
    name: 'Fireplace',
    feature_type: 'structure',
    description: 'A stone fireplace set into the wall.',
  },
  {
    id: 'stone_pillar',
    name: 'Stone Pillar',
    feature_type: 'structure',
    description: 'A heavy stone pillar supporting the structure above.',
  },
  {
    id: 'window',
    name: 'Window',
    feature_type: 'structure',
    description: 'A simple window looking out beyond the room.',
  },
  {
    id: 'wall_torch',
    name: 'Wall Torch',
    feature_type: 'decoration',
    description: 'A wall-mounted torch holder that can provide light when lit.',
  },
  {
    id: 'rug',
    name: 'Rug',
    feature_type: 'decoration',
    description: 'A worn rug spread across part of the floor.',
  },
  {
    id: 'tapestry',
    name: 'Tapestry',
    feature_type: 'decoration',
    description: 'A hanging tapestry used to decorate an otherwise bare wall.',
  },
  {
    id: 'brazier',
    name: 'Brazier',
    feature_type: 'environmental',
    description: 'A metal brazier that can hold a small fire for heat or light.',
  },
];

function isDefaultRoomFeatureTemplate(templateId: string | undefined): boolean {
  return DEFAULT_ROOM_FEATURE_TEMPLATES.some((template) => template.id === templateId);
}

export function FeatureLibraryDialog({
  open,
  templates,
  onOpenChange,
  onSave,
  onDelete,
}: {
  open: boolean;
  templates: RoomFeatureTemplateData[];
  onOpenChange: (open: boolean) => void;
  onSave: (
    editingId: string | undefined,
    record: { name: string; description: string; feature_type: string },
  ) => Promise<boolean>;
  onDelete: (template: RoomFeatureTemplateData) => Promise<boolean>;
}) {
  const [editingId, setEditingId] = useState<string | undefined>();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [featureType, setFeatureType] = useState('furniture');
  const availableTemplates = [
    ...DEFAULT_ROOM_FEATURE_TEMPLATES.filter(
      (preset) => !templates.some((template) => template.id === preset.id),
    ),
    ...templates,
  ];
  const isPersistedEdit = (
    editingId !== undefined && !isDefaultRoomFeatureTemplate(editingId)
  );

  const editTemplate = (template?: RoomFeatureTemplateData) => {
    setEditingId(template?.id);
    setName(template?.name ?? '');
    setDescription(template?.description ?? '');
    setFeatureType(template?.feature_type ?? 'furniture');
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Feature library</DialogTitle>
          <DialogDescription>
            Create reusable room features once, then place independent copies in any room.
          </DialogDescription>
        </DialogHeader>
        <div className="catalog-heading">
          <div className="catalog-count">{availableTemplates.length} feature types available</div>
          <button type="button" onClick={() => editTemplate()}>New feature</button>
        </div>
        <div className="catalog-list" aria-label="Existing room feature types">
          {availableTemplates.map((template) => (
            <button
              type="button"
              className={editingId === template.id ? 'selected' : ''}
              key={template.id}
              onClick={() => editTemplate(template)}
            >
              <span>{template.name}</span>
              <Badge variant="outline">{template.feature_type}</Badge>
            </button>
          ))}
        </div>
        <div className="catalog-grid">
          <label className="dialog-label" htmlFor="feature-template-name">
            Name
            <Input id="feature-template-name" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="dialog-label" htmlFor="feature-template-type">
            Type
            <NativeSelect id="feature-template-type" value={featureType} onChange={(event) => setFeatureType(event.target.value)}>
              <NativeSelectOption value="furniture">furniture</NativeSelectOption>
              <NativeSelectOption value="decoration">decoration</NativeSelectOption>
              <NativeSelectOption value="structure">structure</NativeSelectOption>
              <NativeSelectOption value="environmental">environmental</NativeSelectOption>
              <NativeSelectOption value="other">other</NativeSelectOption>
            </NativeSelect>
          </label>
        </div>
        <label className="dialog-label" htmlFor="feature-template-description">Description</label>
        <Textarea id="feature-template-description" value={description} onChange={(event) => setDescription(event.target.value)} />
        <DialogFooter>
          {isPersistedEdit && (
            <Button
              type="button"
              variant="outline"
              onClick={async () => {
                const template = templates.find((item) => item.id === editingId);
                if (template && await onDelete(template)) editTemplate();
              }}
            >
              <Trash2 /> Delete
            </Button>
          )}
          <Button
            disabled={!name.trim()}
            onClick={async () => {
              if (await onSave(isPersistedEdit ? editingId : undefined, { name, description, feature_type: featureType })) {
                editTemplate();
              }
            }}
          >
            <Save /> {isPersistedEdit ? 'Save feature type' : editingId ? 'Create custom copy' : 'Create feature type'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
