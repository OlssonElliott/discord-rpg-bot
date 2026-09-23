'use client';

import { useState } from 'react';
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
import type { CatalogItem, EnemyTemplateData } from '@/lib/api';
import type { EnemyTemplateDraft } from '../types';

export function EnemyPlacementDialog({
  open,
  templates,
  onOpenChange,
  onPlace,
}: {
  open: boolean;
  templates: EnemyTemplateData[];
  onOpenChange: (open: boolean) => void;
  onPlace: (templateId: string, quantity: number) => Promise<boolean>;
}) {
  const [templateId, setTemplateId] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [search, setSearch] = useState('');
  const filtered = templates.filter((template) => {
    const query = search.trim().toLocaleLowerCase();
    return !query
      || template.name.toLocaleLowerCase().includes(query)
      || template.race.toLocaleLowerCase().includes(query);
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add enemy</DialogTitle>
          <DialogDescription>
            Place independent enemy instances from the shared enemy library.
          </DialogDescription>
        </DialogHeader>

        <label className="dialog-label" htmlFor="enemy-search">
          Search library
        </label>
        <Input
          id="enemy-search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Skeleton, bandit, troll…"
        />

        <label className="dialog-label" htmlFor="enemy-template">
          Enemy type
        </label>
        <NativeSelect
          id="enemy-template"
          value={templateId}
          onChange={(event) => setTemplateId(event.target.value)}
        >
          <NativeSelectOption value="">
            Choose an enemy…
          </NativeSelectOption>
          {filtered.map((template) => (
            <NativeSelectOption
              key={template.id}
              value={template.id}
            >
              {template.name} · {template.race} · {template.max_hp} HP
            </NativeSelectOption>
          ))}
        </NativeSelect>

        <label className="dialog-label" htmlFor="enemy-quantity">
          Quantity
        </label>
        <Input
          id="enemy-quantity"
          type="number"
          min={1}
          max={20}
          value={quantity}
          onChange={(event) => setQuantity(Number(event.target.value))}
        />

        <DialogFooter>
          <Button
            disabled={
              !templateId
              || !Number.isInteger(quantity)
              || quantity < 1
              || quantity > 20
            }
            onClick={async () => {
              if (await onPlace(templateId, quantity)) {
                setTemplateId('');
                setQuantity(1);
                setSearch('');
              }
            }}
          >
            Add {quantity > 1 ? `${quantity} enemies` : 'enemy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function emptyEnemyTemplateDraft(): EnemyTemplateDraft {
  return {
    name: '',
    description: '',
    race: 'Unknown',
    difficulty_level: 1,
    strength: 0,
    dexterity: 0,
    arcana: 0,
    vitality: 0,
    insight: 0,
    personality: 0,
    max_hp: 7,
    armor: 0,
    magical_resistance: 0,
    attack_dc: 12,
    defense_dc: 12,
    damage: '1d4',
    attack_profile: 'Basic attack',
    special_ability: null,
    typical_behaviour: 'Unknown',
    main_hand_item_id: null,
    off_hand_item_id: null,
    armor_item_id: null,
  };
}

export function EnemyLibraryDialog({
  open,
  templates,
  catalogItems,
  onOpenChange,
  onSave,
  onDelete,
}: {
  open: boolean;
  templates: EnemyTemplateData[];
  catalogItems: CatalogItem[];
  onOpenChange: (open: boolean) => void;
  onSave: (
    editingId: string | undefined,
    record: EnemyTemplateDraft,
  ) => Promise<boolean>;
  onDelete: (template: EnemyTemplateData) => Promise<boolean>;
}) {
  const [editingId, setEditingId] = useState<string | undefined>();
  const [draft, setDraft] = useState<EnemyTemplateDraft>(
    () => emptyEnemyTemplateDraft(),
  );
  const editingTemplate = templates.find(
    (template) => template.id === editingId,
  );
  const weapons = catalogItems.filter(
    (item) => item.item_type === 'weapon',
  );
  const armorItems = catalogItems.filter(
    (item) => item.item_type === 'armor',
  );
  const [search, setSearch] = useState('');
  const [raceFilter, setRaceFilter] = useState('all');
  const races = Array.from(
    new Set(templates.map((template) => template.race).filter(Boolean)),
  ).sort((left, right) => left.localeCompare(right));
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredTemplates = templates.filter((template) => (
    (raceFilter === 'all' || template.race === raceFilter)
    && (
      !normalizedSearch
      || template.name.toLocaleLowerCase().includes(normalizedSearch)
      || template.race.toLocaleLowerCase().includes(normalizedSearch)
      || template.typical_behaviour.toLocaleLowerCase().includes(normalizedSearch)
    )
  ));

  function update<K extends keyof EnemyTemplateDraft>(
    key: K,
    value: EnemyTemplateDraft[K],
  ) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function editTemplate(template?: EnemyTemplateData) {
    setEditingId(template?.id);
    setDraft(template ? {
      name: template.name,
      description: template.description,
      race: template.race,
      difficulty_level: template.difficulty_level,
      strength: template.strength,
      dexterity: template.dexterity,
      arcana: template.arcana,
      vitality: template.vitality,
      insight: template.insight,
      personality: template.personality,
      max_hp: template.max_hp,
      armor: template.armor,
      magical_resistance: template.magical_resistance,
      attack_dc: template.attack_dc,
      defense_dc: template.defense_dc,
      damage: template.damage,
      attack_profile: template.attack_profile,
      special_ability: template.special_ability,
      typical_behaviour: template.typical_behaviour,
      main_hand_item_id: template.main_hand_item_id,
      off_hand_item_id: template.off_hand_item_id,
      armor_item_id: template.armor_item_id,
    } : emptyEnemyTemplateDraft());
  }

  const invalidNumber = [
    draft.difficulty_level,
    draft.strength,
    draft.dexterity,
    draft.arcana,
    draft.vitality,
    draft.insight,
    draft.personality,
    draft.armor,
    draft.magical_resistance,
  ].some(
    (value) => !Number.isInteger(value) || value < 0,
  );

  const invalidPositive = [
    draft.max_hp,
    draft.attack_dc,
    draft.defense_dc,
  ].some(
    (value) => !Number.isInteger(value) || value < 1,
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="enemy-library-dialog sm:max-w-[860px]">
        <DialogHeader>
          <DialogTitle>Enemy library</DialogTitle>
          <DialogDescription>
            Define reusable enemy types here. Click an existing type to edit or delete it. Placed copies keep independent HP and world state.
          </DialogDescription>
        </DialogHeader>

        <div className="catalog-heading">
          <div className="catalog-count">
            {filteredTemplates.length} of {templates.length} enemy types
          </div>
          <button
            type="button"
            onClick={() => editTemplate()}
          >
            New enemy
          </button>
        </div>

        <div className="catalog-grid enemy-library-filters">
          <label className="dialog-label" htmlFor="enemy-library-search">
            Search
            <Input
              id="enemy-library-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name, race or behaviour…"
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-library-race">
            Race
            <NativeSelect
              id="enemy-library-race"
              value={raceFilter}
              onChange={(event) => setRaceFilter(event.target.value)}
            >
              <NativeSelectOption value="all">All races</NativeSelectOption>
              {races.map((race) => (
                <NativeSelectOption key={race} value={race}>
                  {race}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
        </div>

        <div
          className="catalog-list"
          aria-label="Existing enemy types"
        >
          {filteredTemplates.map((template) => (
            <button
              type="button"
              className={
                editingId === template.id
                  ? 'selected'
                  : ''
              }
              key={template.id}
              onClick={() => editTemplate(template)}
            >
              <span>{template.name}</span>
              <Badge variant="outline">
                {template.race} · {template.max_hp} HP
              </Badge>
            </button>
          ))}
        </div>

        <div className="catalog-grid">
          <label className="dialog-label" htmlFor="enemy-template-name">
            Name
            <Input
              id="enemy-template-name"
              value={draft.name}
              onChange={(event) => update('name', event.target.value)}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-race">
            Race
            <Input
              id="enemy-template-race"
              value={draft.race}
              onChange={(event) => update('race', event.target.value)}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-difficulty">
            Difficulty
            <Input
              id="enemy-template-difficulty"
              type="number"
              min={0}
              value={draft.difficulty_level}
              onChange={(event) => update('difficulty_level', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-hp">
            Max HP
            <Input
              id="enemy-template-hp"
              type="number"
              min={1}
              value={draft.max_hp}
              onChange={(event) => update('max_hp', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-strength">
            Strength
            <Input
              id="enemy-template-strength"
              type="number"
              min={0}
              value={draft.strength}
              onChange={(event) => update('strength', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-dexterity">
            Dexterity
            <Input
              id="enemy-template-dexterity"
              type="number"
              min={0}
              value={draft.dexterity}
              onChange={(event) => update('dexterity', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-arcana">
            Arcana
            <Input
              id="enemy-template-arcana"
              type="number"
              min={0}
              value={draft.arcana}
              onChange={(event) => update('arcana', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-vitality">
            Vitality
            <Input
              id="enemy-template-vitality"
              type="number"
              min={0}
              value={draft.vitality}
              onChange={(event) => update('vitality', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-insight">
            Insight
            <Input
              id="enemy-template-insight"
              type="number"
              min={0}
              value={draft.insight}
              onChange={(event) => update('insight', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-personality">
            Personality
            <Input
              id="enemy-template-personality"
              type="number"
              min={0}
              value={draft.personality}
              onChange={(event) => update('personality', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-armor">
            Armor
            <Input
              id="enemy-template-armor"
              type="number"
              min={0}
              value={draft.armor}
              onChange={(event) => update('armor', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-magic-resistance">
            Magic resistance
            <Input
              id="enemy-template-magic-resistance"
              type="number"
              min={0}
              value={draft.magical_resistance}
              onChange={(event) => update('magical_resistance', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-attack-dc">
            Attack DC
            <Input
              id="enemy-template-attack-dc"
              type="number"
              min={1}
              value={draft.attack_dc}
              onChange={(event) => update('attack_dc', Number(event.target.value))}
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-template-defense-dc">
            Defense DC
            <Input
              id="enemy-template-defense-dc"
              type="number"
              min={1}
              value={draft.defense_dc}
              onChange={(event) => update('defense_dc', Number(event.target.value))}
            />
          </label>
        </div>

        <label className="dialog-label" htmlFor="enemy-template-description">
          Description
        </label>
        <Textarea
          id="enemy-template-description"
          value={draft.description}
          onChange={(event) => update('description', event.target.value)}
        />

        <label className="dialog-label" htmlFor="enemy-template-damage">
          Damage
        </label>
        <Input
          id="enemy-template-damage"
          value={draft.damage}
          onChange={(event) => update('damage', event.target.value)}
          placeholder="1d6"
        />

        <label className="dialog-label" htmlFor="enemy-template-attack-profile">
          Attack profile
        </label>
        <Input
          id="enemy-template-attack-profile"
          value={draft.attack_profile}
          onChange={(event) => update('attack_profile', event.target.value)}
        />

        <label className="dialog-label" htmlFor="enemy-template-behaviour">
          Typical behaviour
        </label>
        <Textarea
          id="enemy-template-behaviour"
          value={draft.typical_behaviour}
          onChange={(event) => update('typical_behaviour', event.target.value)}
        />

        <label className="dialog-label" htmlFor="enemy-template-ability">
          Special ability
        </label>
        <Textarea
          id="enemy-template-ability"
          value={draft.special_ability ?? ''}
          onChange={(event) => update(
            'special_ability',
            event.target.value.trim()
              ? event.target.value
              : null,
          )}
        />

        <div className="catalog-grid">
          <label className="dialog-label" htmlFor="enemy-template-main-hand">
            Main hand
            <NativeSelect
              id="enemy-template-main-hand"
              value={draft.main_hand_item_id ?? ''}
              onChange={(event) => update(
                'main_hand_item_id',
                event.target.value || null,
              )}
            >
              <NativeSelectOption value="">None</NativeSelectOption>
              {weapons.map((item) => (
                <NativeSelectOption key={item.id} value={item.id}>
                  {item.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>

          <label className="dialog-label" htmlFor="enemy-template-off-hand">
            Off hand
            <NativeSelect
              id="enemy-template-off-hand"
              value={draft.off_hand_item_id ?? ''}
              onChange={(event) => update(
                'off_hand_item_id',
                event.target.value || null,
              )}
            >
              <NativeSelectOption value="">None</NativeSelectOption>
              {weapons.map((item) => (
                <NativeSelectOption key={item.id} value={item.id}>
                  {item.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>

          <label className="dialog-label" htmlFor="enemy-template-armor-item">
            Armor
            <NativeSelect
              id="enemy-template-armor-item"
              value={draft.armor_item_id ?? ''}
              onChange={(event) => update(
                'armor_item_id',
                event.target.value || null,
              )}
            >
              <NativeSelectOption value="">None</NativeSelectOption>
              {armorItems.map((item) => (
                <NativeSelectOption key={item.id} value={item.id}>
                  {item.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
        </div>

        <DialogFooter className="enemy-library-footer">
          {editingTemplate && (
            <Button
              variant="destructive"
              onClick={async () => {
                if (await onDelete(editingTemplate)) {
                  editTemplate();
                }
              }}
            >
              <Trash2 /> Delete
            </Button>
          )}

          <Button
            disabled={
              !draft.name.trim()
              || !draft.race.trim()
              || !draft.damage.trim()
              || !draft.attack_profile.trim()
              || !draft.typical_behaviour.trim()
              || invalidNumber
              || invalidPositive
            }
            onClick={async () => {
              if (await onSave(editingId, draft)) {
                editTemplate();
              }
            }}
          >
            <Save />
            {editingId
              ? 'Save enemy type'
              : 'Create enemy type'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
