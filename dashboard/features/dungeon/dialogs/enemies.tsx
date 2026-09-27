'use client';

import { useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight, Save, Trash2 } from 'lucide-react';
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
  onPlace: (
    templateId: string,
    quantity: number,
    combatRole: 'random' | 'melee' | 'ranged' | 'spellcaster',
  ) => Promise<boolean>;
}) {
  const [templateId, setTemplateId] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [combatRole, setCombatRole] = useState<'random' | 'melee' | 'ranged' | 'spellcaster'>('random');
  const [search, setSearch] = useState('');
  const selectedTemplate = templates.find((template) => template.id === templateId);
  const availableRoles = selectedTemplate?.available_roles ?? [];
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
          onChange={(event) => {
            setTemplateId(event.target.value);
            setCombatRole('random');
          }}
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

        {selectedTemplate && (
          <>
            <label className="dialog-label" htmlFor="enemy-combat-role">
              Combat role
            </label>
            <NativeSelect
              id="enemy-combat-role"
              value={availableRoles.length <= 1 ? (availableRoles[0] ?? 'melee') : combatRole}
              onChange={(event) => setCombatRole(
                event.target.value as 'random' | 'melee' | 'ranged' | 'spellcaster',
              )}
            >
              {availableRoles.length > 1 && (
                <NativeSelectOption value="random">Random</NativeSelectOption>
              )}
              {availableRoles.includes('melee') && (
                <NativeSelectOption value="melee">Melee</NativeSelectOption>
              )}
              {availableRoles.includes('ranged') && (
                <NativeSelectOption value="ranged">Ranged</NativeSelectOption>
              )}
              {availableRoles.includes('spellcaster') && (
                <NativeSelectOption value="spellcaster">Spellcaster</NativeSelectOption>
              )}
              {availableRoles.length === 0 && (
                <NativeSelectOption value="melee">Melee</NativeSelectOption>
              )}
            </NativeSelect>
          </>
        )}

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
              const role = availableRoles.length <= 1
                ? (availableRoles[0] ?? 'melee')
                : combatRole;
              if (await onPlace(templateId, quantity, role)) {
                setTemplateId('');
                setQuantity(1);
                setCombatRole('random');
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
    melee_weapon_ids: [],
    ranged_weapon_ids: [],
    off_hand_item_ids: [],
    armor_item_ids: [],
    spell_names: [],
    spell_range: 3,
  };
}

function EnemyEditorSection({
  title,
  summary,
  defaultOpen = false,
  children,
}: {
  title: string;
  summary?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="enemy-editor-section">
      <button
        type="button"
        className="enemy-editor-section__toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span>{title}</span>
        {summary && <Badge variant="outline">{summary}</Badge>}
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {open && <div className="enemy-editor-section__body">{children}</div>}
    </section>
  );
}

function PoolChecklist({
  items,
  selected,
  onChange,
}: {
  items: CatalogItem[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  if (!items.length) {
    return <p className="enemy-pool-empty">No compatible items in the Item Library.</p>;
  }
  return (
    <div className="enemy-pool-list">
      {items.map((item) => (
        <label key={item.id} className="enemy-pool-option">
          <input
            type="checkbox"
            checked={selected.includes(item.id)}
            onChange={(event) => {
              onChange(
                event.target.checked
                  ? [...selected, item.id]
                  : selected.filter((id) => id !== item.id),
              );
            }}
          />
          <span>{item.name}</span>
          {item.item_type === 'weapon' && (
            <small>Range {item.range ?? 0}</small>
          )}
        </label>
      ))}
    </div>
  );
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
  const [search, setSearch] = useState('');
  const [raceFilter, setRaceFilter] = useState('all');
  const editingTemplate = templates.find((template) => template.id === editingId);

  const weapons = catalogItems.filter((item) => item.item_type === 'weapon');
  const meleeWeapons = weapons.filter((item) => (item.range ?? 0) <= 0);
  const rangedWeapons = weapons.filter((item) => (item.range ?? 0) > 0);
  const armorItems = catalogItems.filter((item) => item.item_type === 'armor');

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
    if (!template) {
      setDraft(emptyEnemyTemplateDraft());
      return;
    }

    const legacyMain = template.main_hand_item_id
      ? catalogItems.find((item) => item.id === template.main_hand_item_id)
      : undefined;
    const meleePool = [...template.melee_weapon_ids];
    const rangedPool = [...template.ranged_weapon_ids];
    if (legacyMain && !meleePool.includes(legacyMain.id) && !rangedPool.includes(legacyMain.id)) {
      ((legacyMain.range ?? 0) > 0 ? rangedPool : meleePool).push(legacyMain.id);
    }

    setDraft({
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
      main_hand_item_id: null,
      off_hand_item_id: null,
      armor_item_id: null,
      melee_weapon_ids: meleePool,
      ranged_weapon_ids: rangedPool,
      off_hand_item_ids: Array.from(new Set([
        ...template.off_hand_item_ids,
        ...(template.off_hand_item_id ? [template.off_hand_item_id] : []),
      ])),
      armor_item_ids: Array.from(new Set([
        ...template.armor_item_ids,
        ...(template.armor_item_id ? [template.armor_item_id] : []),
      ])),
      spell_names: template.spell_names,
      spell_range: template.spell_range,
    });
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
  ].some((value) => !Number.isInteger(value) || value < 0);
  const invalidPositive = [
    draft.max_hp,
    draft.attack_dc,
    draft.defense_dc,
    draft.spell_range,
  ].some((value) => !Number.isInteger(value) || value < 1);

  const roleSummary = [
    draft.melee_weapon_ids.length ? 'Melee' : '',
    draft.ranged_weapon_ids.length ? 'Ranged' : '',
    draft.spell_names.length ? 'Spellcaster' : '',
  ].filter(Boolean).join(' · ') || 'No roles';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="enemy-library-dialog sm:max-w-[860px]">
        <DialogHeader>
          <DialogTitle>Enemy library</DialogTitle>
          <DialogDescription>
            Define reusable enemy types and the combat roles their placed instances may use.
          </DialogDescription>
        </DialogHeader>

        <div className="catalog-heading">
          <div className="catalog-count">
            {filteredTemplates.length} of {templates.length} enemy types
          </div>
          <button type="button" onClick={() => editTemplate()}>
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
                <NativeSelectOption key={race} value={race}>{race}</NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
        </div>

        <div className="catalog-list" aria-label="Existing enemy types">
          {filteredTemplates.map((template) => (
            <button
              type="button"
              className={editingId === template.id ? 'selected' : ''}
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

        <div className="enemy-editor-sections">
          <EnemyEditorSection title="Basics" summary={draft.race} defaultOpen>
            <div className="catalog-grid">
              <label className="dialog-label">Name
                <Input value={draft.name} onChange={(event) => update('name', event.target.value)} />
              </label>
              <label className="dialog-label">Race
                <Input value={draft.race} onChange={(event) => update('race', event.target.value)} />
              </label>
              <label className="dialog-label">Difficulty
                <Input type="number" min={0} value={draft.difficulty_level} onChange={(event) => update('difficulty_level', Number(event.target.value))} />
              </label>
              <label className="dialog-label">Max HP
                <Input type="number" min={1} value={draft.max_hp} onChange={(event) => update('max_hp', Number(event.target.value))} />
              </label>
            </div>
            <label className="dialog-label">Description
              <Textarea value={draft.description} onChange={(event) => update('description', event.target.value)} />
            </label>
          </EnemyEditorSection>

          <EnemyEditorSection title="Attribute modifiers" summary="STR · DEX · ARC · VIT · INS · PER">
            <p className="enemy-section-help">These values are modifiers, not 1–20 character attribute scores.</p>
            <div className="enemy-attribute-grid">
              {([
                ['strength', 'STR'],
                ['dexterity', 'DEX'],
                ['arcana', 'ARC'],
                ['vitality', 'VIT'],
                ['insight', 'INS'],
                ['personality', 'PER'],
              ] as const).map(([key, abbreviation]) => (
                <label key={key}>
                  <span>{abbreviation}</span>
                  <Input
                    type="number"
                    min={0}
                    value={draft[key]}
                    onChange={(event) => update(key, Number(event.target.value))}
                  />
                </label>
              ))}
            </div>
          </EnemyEditorSection>

          <EnemyEditorSection title="Combat" summary={`ATK ${draft.attack_dc} · DEF ${draft.defense_dc}`}>
            <div className="catalog-grid">
              <label className="dialog-label">Armor
                <Input type="number" min={0} value={draft.armor} onChange={(event) => update('armor', Number(event.target.value))} />
              </label>
              <label className="dialog-label">Magic resistance
                <Input type="number" min={0} value={draft.magical_resistance} onChange={(event) => update('magical_resistance', Number(event.target.value))} />
              </label>
              <label className="dialog-label">Attack DC
                <Input type="number" min={1} value={draft.attack_dc} onChange={(event) => update('attack_dc', Number(event.target.value))} />
              </label>
              <label className="dialog-label">Defense DC
                <Input type="number" min={1} value={draft.defense_dc} onChange={(event) => update('defense_dc', Number(event.target.value))} />
              </label>
              <label className="dialog-label">Damage
                <Input value={draft.damage} onChange={(event) => update('damage', event.target.value)} placeholder="1d6" />
              </label>
              <label className="dialog-label">Attack profile
                <Input value={draft.attack_profile} onChange={(event) => update('attack_profile', event.target.value)} />
              </label>
            </div>
          </EnemyEditorSection>

          <EnemyEditorSection title="Loadout pools" summary={roleSummary}>
            <p className="enemy-section-help">
              A placed enemy receives one random item from the selected role pool. Its actual loadout is then saved on that enemy instance.
            </p>
            <div className="enemy-pool-grid">
              <div>
                <h4>Melee weapons</h4>
                <PoolChecklist items={meleeWeapons} selected={draft.melee_weapon_ids} onChange={(value) => update('melee_weapon_ids', value)} />
              </div>
              <div>
                <h4>Ranged weapons</h4>
                <PoolChecklist items={rangedWeapons} selected={draft.ranged_weapon_ids} onChange={(value) => update('ranged_weapon_ids', value)} />
              </div>
              <div>
                <h4>Off hand</h4>
                <PoolChecklist items={weapons} selected={draft.off_hand_item_ids} onChange={(value) => update('off_hand_item_ids', value)} />
              </div>
              <div>
                <h4>Armor</h4>
                <PoolChecklist items={armorItems} selected={draft.armor_item_ids} onChange={(value) => update('armor_item_ids', value)} />
              </div>
            </div>
          </EnemyEditorSection>

          <EnemyEditorSection title="Magic" summary={draft.spell_names.length ? `${draft.spell_names.length} spells` : 'None'}>
            <p className="enemy-section-help">
              Spell names currently define Spellcaster access and attack range. A full spell library can replace this list later.
            </p>
            <label className="dialog-label">Spell access
              <Input
                value={draft.spell_names.join(', ')}
                placeholder="Dark Bolt, Fear, Hex"
                onChange={(event) => update(
                  'spell_names',
                  Array.from(new Set(
                    event.target.value.split(',').map((value) => value.trim()).filter(Boolean),
                  )),
                )}
              />
            </label>
            <label className="dialog-label">Spell range
              <Input type="number" min={1} value={draft.spell_range} onChange={(event) => update('spell_range', Number(event.target.value))} />
            </label>
          </EnemyEditorSection>

          <EnemyEditorSection title="Behaviour">
            <label className="dialog-label">Typical behaviour
              <Textarea value={draft.typical_behaviour} onChange={(event) => update('typical_behaviour', event.target.value)} />
            </label>
            <label className="dialog-label">Special ability
              <Textarea
                value={draft.special_ability ?? ''}
                onChange={(event) => update('special_ability', event.target.value.trim() ? event.target.value : null)}
              />
            </label>
          </EnemyEditorSection>
        </div>

        <DialogFooter className="enemy-library-footer">
          {editingTemplate && (
            <Button
              variant="destructive"
              onClick={async () => {
                if (await onDelete(editingTemplate)) editTemplate();
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
              if (await onSave(editingId, draft)) editTemplate();
            }}
          >
            <Save />
            {editingId ? 'Save enemy type' : 'Create enemy type'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
