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

const LINEAGE_RACES: Record<string, string[]> = {
  Commonfolk: ['Human', 'Dwarf', 'Halfling'],
  Fey: ['Elf', 'Dryad', 'Faun'],
  Primals: ['Gnoll', 'Lizardman', 'Minotaur'],
  Felblood: ['Orc', 'Troll', 'Goblin'],
  Wretched: ['Revenant', 'Hagspawn', 'Swarmling'],
  Other: ['Undead', 'Undead Beast', 'Beast', 'Construct', 'Aberration', 'Demon', 'Elemental', 'Unknown'],
};

const ATTRIBUTE_PRESETS = {
  Balanced: { strength: 2, dexterity: 2, arcana: 1, vitality: 2, insight: 1, personality: 1 },
  Melee: { strength: 4, dexterity: 2, arcana: 0, vitality: 3, insight: 1, personality: 1 },
  Ranged: { strength: 1, dexterity: 4, arcana: 0, vitality: 2, insight: 2, personality: 1 },
  Tank: { strength: 3, dexterity: 1, arcana: 0, vitality: 4, insight: 2, personality: 1 },
} as const;

const NATURAL_ATTACK_PRESETS = {
  bite: { name: 'Bite', damage: '1d6', damage_type: 'pierce', range: 0 },
  claws: { name: 'Claws', damage: '1d6', damage_type: 'slash', range: 0 },
  gore: { name: 'Gore', damage: '1d8', damage_type: 'pierce', range: 0 },
  slam: { name: 'Slam', damage: '1d6', damage_type: 'blunt', range: 0 },
} as const;

function lineageForRace(race: string): string {
  return Object.entries(LINEAGE_RACES).find(([, races]) => (
    races.includes(race)
  ))?.[0] ?? 'Other';
}


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
    lineage: 'Other',
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
    melee_damage_filter: null,
    ranged_damage_filter: null,
    natural_attacks: [],
    armor_reduction_filter: null,
    dual_wield: false,
    allowed_races: [],
    melee_loadouts: [],
    shield_item_ids: [],
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
    return (
      <div className="enemy-pool-list enemy-pool-list--empty">
        <p className="enemy-pool-empty">No compatible items in the Item Library.</p>
      </div>
    );
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
            <small>
              {item.damage_expression ?? `1d${item.damage ?? 1}`}
              {item.damage_type ? ` · ${item.damage_type}` : ''}
              {` · Range ${item.range ?? 0}`}
            </small>
          )}
          {item.item_type === 'armor' && (
            <small>
              {(item.defense_bonus ?? 0) > 0
                ? `Defense +${item.defense_bonus}`
                : `DR ${item.protection ?? 0} · Dodge ${(item.dodge_penalty ?? 0) >= 0 ? '+' : ''}${item.dodge_penalty ?? 0}`}
            </small>
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
  const [lineageFilter, setLineageFilter] = useState('all');
  const [raceFilter, setRaceFilter] = useState('all');
  const [naturalAttackPreset, setNaturalAttackPreset] = useState<keyof typeof NATURAL_ATTACK_PRESETS>('bite');
  const editingTemplate = templates.find((template) => template.id === editingId);

  const weapons = catalogItems.filter((item) => item.item_type === 'weapon');
  const meleeWeapons = weapons.filter((item) => (item.range ?? 0) <= 0);
  const rangedWeapons = weapons.filter((item) => (item.range ?? 0) > 0);
  const armorItems = catalogItems.filter((item) => item.item_type === 'armor');
  const bodyArmorItems = armorItems.filter((item) => (item.defense_bonus ?? 0) <= 0);
  const shieldItems = armorItems.filter((item) => (item.defense_bonus ?? 0) > 0);
  const secondWeapons = meleeWeapons.filter(
    (item) => item.grip === 'one_handed',
  );
  const meleeDamageOptions = Array.from(new Set(
    meleeWeapons.map((item) => item.damage_expression).filter(Boolean),
  )).sort();
  const rangedDamageOptions = Array.from(new Set(
    rangedWeapons.map((item) => item.damage_expression).filter(Boolean),
  )).sort();
  const compatibleMeleeWeapons = meleeWeapons.filter(
    (item) => !draft.melee_damage_filter
      || item.damage_expression === draft.melee_damage_filter,
  );
  const compatibleRangedWeapons = rangedWeapons.filter(
    (item) => !draft.ranged_damage_filter
      || item.damage_expression === draft.ranged_damage_filter,
  );
  const armorReductionOptions = Array.from(new Set(
    bodyArmorItems
      .map((item) => item.protection)
      .filter((value): value is number => value !== undefined),
  )).sort((left, right) => left - right);
  const compatibleArmorItems = bodyArmorItems.filter(
    (item) => draft.armor_reduction_filter === null
      || item.protection === draft.armor_reduction_filter,
  );
  const selectedArmorItems = bodyArmorItems.filter(
    (item) => draft.armor_item_ids.includes(item.id),
  );
  const selectedShieldItems = shieldItems.filter(
    (item) => draft.shield_item_ids.includes(item.id),
  );
  const armorChoices = selectedArmorItems.length ? selectedArmorItems : [undefined];
  const shieldChoices = draft.melee_loadouts.includes('shield')
    ? (selectedShieldItems.length ? selectedShieldItems : [undefined])
    : [undefined];
  const defenseValues = Array.from(new Set(
    armorChoices.flatMap((armor) => (
      shieldChoices.map((shield) => Math.max(
        1,
        10
          + draft.dexterity
          + (armor?.dodge_penalty ?? 0)
          + (shield?.defense_bonus ?? 0),
      ))
    )),
  )).sort((left, right) => left - right);
  const defenseSummary = defenseValues.length > 1
    ? `${defenseValues[0]}–${defenseValues[defenseValues.length - 1]}`
    : String(defenseValues[0] ?? (10 + draft.dexterity));
  const meleeAttackDc = Math.max(1, 10 + draft.strength);
  const rangedAttackDc = Math.max(1, 10 + draft.dexterity);

  const lineages = Object.keys(LINEAGE_RACES);
  const races = Array.from(new Set([
    ...(lineageFilter === 'all'
      ? Object.values(LINEAGE_RACES).flat()
      : (LINEAGE_RACES[lineageFilter] ?? [])),
    ...templates
      .filter((template) => lineageFilter === 'all' || template.lineage === lineageFilter)
      .map((template) => template.race),
  ].filter(Boolean))).sort((left, right) => left.localeCompare(right));
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredTemplates = templates.filter((template) => (
    (lineageFilter === 'all' || template.lineage === lineageFilter)
    && (raceFilter === 'all' || template.race === raceFilter)
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
      setNaturalAttackPreset('bite');
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

    const rawOffhandIds = Array.from(new Set([
      ...template.off_hand_item_ids,
      ...(template.off_hand_item_id ? [template.off_hand_item_id] : []),
    ]));
    const existingShieldIds = Array.from(new Set([
      ...template.shield_item_ids,
      ...rawOffhandIds.filter((id) => (
        (catalogItems.find((item) => item.id === id)?.defense_bonus ?? 0) > 0
      )),
    ]));
    const existingSecondWeaponIds = rawOffhandIds.filter((id) => (
      (catalogItems.find((item) => item.id === id)?.defense_bonus ?? 0) <= 0
    ));
    const oneHandedPool = meleePool.filter((id) => (
      catalogItems.find((item) => item.id === id)?.grip === 'one_handed'
    ));
    const twoHandedPool = meleePool.filter((id) => (
      catalogItems.find((item) => item.id === id)?.grip === 'two_handed'
    ));
    const inferredLoadouts = [
      oneHandedPool.length ? 'one_handed' : '',
      existingShieldIds.length && oneHandedPool.length ? 'shield' : '',
      existingSecondWeaponIds.length && oneHandedPool.length ? 'dual_wield' : '',
      twoHandedPool.length ? 'two_handed' : '',
      template.natural_attacks.length ? 'natural' : '',
    ].filter(Boolean) as EnemyTemplateDraft['melee_loadouts'];
    const selectedLoadouts = template.melee_loadouts.length
      ? template.melee_loadouts
      : inferredLoadouts;
    const selectedRaces = template.allowed_races.length
      ? template.allowed_races
      : [template.race];

    setDraft({
      name: template.name,
      description: template.description,
      race: template.race,
      lineage: template.lineage,
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
      off_hand_item_ids: existingSecondWeaponIds,
      armor_item_ids: Array.from(new Set([
        ...template.armor_item_ids,
        ...(template.armor_item_id ? [template.armor_item_id] : []),
      ])),
      spell_names: template.spell_names,
      spell_range: template.spell_range,
      melee_damage_filter: template.melee_damage_filter,
      ranged_damage_filter: template.ranged_damage_filter,
      natural_attacks: template.natural_attacks,
      armor_reduction_filter: template.armor_reduction_filter,
      dual_wield: selectedLoadouts.includes('dual_wield'),
      allowed_races: selectedRaces,
      melee_loadouts: selectedLoadouts,
      shield_item_ids: existingShieldIds,
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

  const attributePreset = (
    Object.entries(ATTRIBUTE_PRESETS).find(([, values]) => (
      draft.strength === values.strength
      && draft.dexterity === values.dexterity
      && draft.arcana === values.arcana
      && draft.vitality === values.vitality
      && draft.insight === values.insight
      && draft.personality === values.personality
    ))?.[0] ?? 'Custom'
  );

  function applyAttributePreset(name: string) {
    if (name === 'Custom') return;
    const preset = ATTRIBUTE_PRESETS[name as keyof typeof ATTRIBUTE_PRESETS];
    setDraft((current) => ({ ...current, ...preset }));
  }

  const roleSummary = [
    draft.melee_loadouts.length ? 'Melee' : '',
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

        <div className="enemy-library-filter-grid">
          <label className="dialog-label" htmlFor="enemy-library-search">
            Search
            <Input
              id="enemy-library-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name, race or behaviour…"
            />
          </label>
          <label className="dialog-label" htmlFor="enemy-library-lineage">
            Lineage
            <NativeSelect
              id="enemy-library-lineage"
              value={lineageFilter}
              onChange={(event) => {
                setLineageFilter(event.target.value);
                setRaceFilter('all');
              }}
            >
              <NativeSelectOption value="all">All lineages</NativeSelectOption>
              {lineages.map((lineage) => (
                <NativeSelectOption key={lineage} value={lineage}>
                  {lineage}
                </NativeSelectOption>
              ))}
            </NativeSelect>
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
                {template.lineage} · {template.race} · {template.max_hp} HP
              </Badge>
            </button>
          ))}
        </div>

        <div className="enemy-editor-sections">
          <EnemyEditorSection
            title="Basics"
            summary={`${draft.allowed_races.length || 1} race${(draft.allowed_races.length || 1) === 1 ? '' : 's'}`}
            defaultOpen
          >
            <div className="catalog-grid">
              <label className="dialog-label">Name
                <Input value={draft.name} onChange={(event) => update('name', event.target.value)} />
              </label>
              <label className="dialog-label">Max HP
                <Input type="number" min={1} value={draft.max_hp} onChange={(event) => update('max_hp', Number(event.target.value))} />
              </label>
              <label className="dialog-label">Difficulty
                <Input value="Not calculated yet" disabled />
              </label>
              <label className="dialog-label">Magic resistance
                <Input
                  type="number"
                  min={0}
                  value={draft.magical_resistance}
                  onChange={(event) => update('magical_resistance', Number(event.target.value))}
                />
              </label>
            </div>

            <div className="enemy-race-pool">
              <div className="enemy-race-pool__heading">
                <div>
                  <strong>Allowed races</strong>
                  <p className="enemy-section-help">
                    One race is chosen and saved when the enemy spawns.
                  </p>
                </div>
                <Badge variant="outline">
                  {draft.allowed_races.length || 1} selected
                </Badge>
              </div>
              <div className="enemy-race-groups">
                {Object.entries(LINEAGE_RACES).map(([lineage, races]) => {
                  const selectedCount = races.filter((race) => (
                    draft.allowed_races.includes(race)
                  )).length;
                  const allSelected = selectedCount === races.length;
                  return (
                    <div key={lineage} className="enemy-race-group">
                      <label className="enemy-race-group__title">
                        <input
                          type="checkbox"
                          checked={allSelected}
                          onChange={(event) => {
                            const withoutGroup = draft.allowed_races.filter(
                              (race) => !races.includes(race),
                            );
                            const next = event.target.checked
                              ? [...withoutGroup, ...races]
                              : withoutGroup;
                            const fallback = next[0] ?? 'Unknown';
                            update('allowed_races', next);
                            update('race', fallback);
                            update('lineage', lineageForRace(fallback));
                          }}
                        />
                        <span>{lineage}</span>
                        <small>{selectedCount}/{races.length}</small>
                      </label>
                      <div className="enemy-race-options">
                        {races.map((race) => (
                          <label key={race}>
                            <input
                              type="checkbox"
                              checked={draft.allowed_races.includes(race)}
                              onChange={(event) => {
                                const next = event.target.checked
                                  ? [...draft.allowed_races, race]
                                  : draft.allowed_races.filter((value) => value !== race);
                                const fallback = next[0] ?? 'Unknown';
                                update('allowed_races', next);
                                update('race', fallback);
                                update('lineage', lineageForRace(fallback));
                              }}
                            />
                            <span>{race}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <label className="dialog-label">Description
              <Textarea value={draft.description} onChange={(event) => update('description', event.target.value)} />
            </label>
            <div className="enemy-combat-summary">
              <div>
                <span>Melee Attack DC</span>
                <strong>{meleeAttackDc}</strong>
                <small>10 + STR {draft.strength}</small>
              </div>
              <div>
                <span>Ranged Attack DC</span>
                <strong>{rangedAttackDc}</strong>
                <small>10 + DEX {draft.dexterity}</small>
              </div>
              <div>
                <span>Defense DC</span>
                <strong>{defenseSummary}</strong>
                <small>10 + DEX + armor + shield</small>
              </div>
            </div>
          </EnemyEditorSection>

          <EnemyEditorSection title="Attribute modifiers" summary="STR · DEX · ARC · VIT · INS · PER">
            <div className="enemy-attribute-heading">
              <p className="enemy-section-help">These values are modifiers, not 1–20 character attribute scores.</p>
              <label className="dialog-label enemy-preset-control">
                Preset
                <NativeSelect
                  value={attributePreset}
                  onChange={(event) => applyAttributePreset(event.target.value)}
                >
                  {Object.keys(ATTRIBUTE_PRESETS).map((preset) => (
                    <NativeSelectOption key={preset} value={preset}>
                      {preset}
                    </NativeSelectOption>
                  ))}
                  <NativeSelectOption value="Custom">Custom</NativeSelectOption>
                </NativeSelect>
              </label>
            </div>
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

          <EnemyEditorSection title="Loadout pools" summary={roleSummary}>
            <p className="enemy-section-help">
              Desired damage filters the Item Library. Combat damage still comes from the actual weapon selected when this enemy spawns.
            </p>
            <div className="enemy-pool-grid">
              <div>
                <h4>Melee weapons</h4>
                <label className="dialog-label">
                  Desired damage
                  <NativeSelect
                    value={draft.melee_damage_filter ?? ''}
                    onChange={(event) => {
                      const next = event.target.value || null;
                      update('melee_damage_filter', next);
                      update(
                        'melee_weapon_ids',
                        draft.melee_weapon_ids.filter((id) => {
                          const item = meleeWeapons.find((candidate) => candidate.id === id);
                          return !next || item?.damage_expression === next;
                        }),
                      );
                    }}
                  >
                    <NativeSelectOption value="">Any damage</NativeSelectOption>
                    {meleeDamageOptions.map((damage) => (
                      <NativeSelectOption key={damage} value={damage}>{damage}</NativeSelectOption>
                    ))}
                  </NativeSelect>
                </label>
                <PoolChecklist
                  items={compatibleMeleeWeapons}
                  selected={draft.melee_weapon_ids}
                  onChange={(value) => update('melee_weapon_ids', value)}
                />
              </div>

              <div>
                <h4>Ranged weapons</h4>
                <label className="dialog-label">
                  Desired damage
                  <NativeSelect
                    value={draft.ranged_damage_filter ?? ''}
                    onChange={(event) => {
                      const next = event.target.value || null;
                      update('ranged_damage_filter', next);
                      update(
                        'ranged_weapon_ids',
                        draft.ranged_weapon_ids.filter((id) => {
                          const item = rangedWeapons.find((candidate) => candidate.id === id);
                          return !next || item?.damage_expression === next;
                        }),
                      );
                    }}
                  >
                    <NativeSelectOption value="">Any damage</NativeSelectOption>
                    {rangedDamageOptions.map((damage) => (
                      <NativeSelectOption key={damage} value={damage}>{damage}</NativeSelectOption>
                    ))}
                  </NativeSelect>
                </label>
                <PoolChecklist
                  items={compatibleRangedWeapons}
                  selected={draft.ranged_weapon_ids}
                  onChange={(value) => update('ranged_weapon_ids', value)}
                />
              </div>

              <div>
                <h4>Offhand</h4>
                <label className="dialog-label">
                  Mode
                  <NativeSelect
                    value={offhandMode}
                    onChange={(event) => {
                      const mode = event.target.value as 'none' | 'dual_wield' | 'shield';
                      setOffhandMode(mode);
                      update('dual_wield', mode === 'dual_wield');
                      update('off_hand_item_ids', []);
                      if (mode !== 'none') {
                        update(
                          'melee_weapon_ids',
                          draft.melee_weapon_ids.filter((id) => (
                            meleeWeapons.find((item) => item.id === id)?.grip === 'one_handed'
                          )),
                        );
                      }
                    }}
                  >
                    <NativeSelectOption value="none">None</NativeSelectOption>
                    <NativeSelectOption value="dual_wield">Dual wield</NativeSelectOption>
                    <NativeSelectOption value="shield">Shield</NativeSelectOption>
                  </NativeSelect>
                </label>
                {offhandMode === 'dual_wield' && (
                  <PoolChecklist
                    items={secondWeapons}
                    selected={draft.off_hand_item_ids}
                    onChange={(value) => update('off_hand_item_ids', value)}
                  />
                )}
                {offhandMode === 'shield' && (
                  <PoolChecklist
                    items={shieldItems}
                    selected={draft.off_hand_item_ids}
                    onChange={(value) => update('off_hand_item_ids', value)}
                  />
                )}
                {offhandMode === 'none' && (
                  <div className="enemy-pool-list enemy-pool-list--empty">
                    <p className="enemy-pool-empty">
                      No offhand equipment.
                    </p>
                  </div>
                )}
              </div>
              <div>
                <h4>Armor</h4>
                <label className="dialog-label">
                  Desired damage reduction
                  <NativeSelect
                    value={draft.armor_reduction_filter ?? ''}
                    onChange={(event) => {
                      const next = event.target.value === ''
                        ? null
                        : Number(event.target.value);
                      update('armor_reduction_filter', next);
                      update(
                        'armor_item_ids',
                        draft.armor_item_ids.filter((id) => {
                          const item = armorItems.find((candidate) => candidate.id === id);
                          return next === null || item?.protection === next;
                        }),
                      );
                    }}
                  >
                    <NativeSelectOption value="">Any reduction</NativeSelectOption>
                    {armorReductionOptions.map((reduction) => (
                      <NativeSelectOption key={reduction} value={reduction}>
                        DR {reduction}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </label>
                <PoolChecklist
                  items={compatibleArmorItems}
                  selected={draft.armor_item_ids}
                  onChange={(value) => update('armor_item_ids', value)}
                />
              </div>
            </div>

            <div className="enemy-natural-attacks">
              <div className="enemy-natural-attacks__heading">
                <div>
                  <h4>Natural attacks</h4>
                  <p className="enemy-section-help">
                    Natural attacks belong to the creature and are not placed in inventory or loot.
                  </p>
                </div>
                <div className="enemy-natural-preset">
                  <NativeSelect
                    value={naturalAttackPreset}
                    onChange={(event) => setNaturalAttackPreset(
                      event.target.value as keyof typeof NATURAL_ATTACK_PRESETS,
                    )}
                  >
                    {Object.entries(NATURAL_ATTACK_PRESETS).map(([id, attack]) => (
                      <NativeSelectOption key={id} value={id}>
                        {attack.name} · {attack.damage}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => update('natural_attacks', [
                      ...draft.natural_attacks,
                      { ...NATURAL_ATTACK_PRESETS[naturalAttackPreset] },
                    ])}
                  >
                    Add
                  </Button>
                </div>
              </div>
              {draft.natural_attacks.map((attack, index) => (
                <div className="enemy-natural-attack-row" key={`${index}-${attack.name}`}>
                  <Input
                    aria-label="Natural attack name"
                    value={attack.name}
                    placeholder="Bite"
                    onChange={(event) => update(
                      'natural_attacks',
                      draft.natural_attacks.map((entry, entryIndex) => (
                        entryIndex === index
                          ? { ...entry, name: event.target.value }
                          : entry
                      )),
                    )}
                  />
                  <Input
                    aria-label="Natural attack damage"
                    value={attack.damage}
                    placeholder="1d6"
                    onChange={(event) => update(
                      'natural_attacks',
                      draft.natural_attacks.map((entry, entryIndex) => (
                        entryIndex === index
                          ? { ...entry, damage: event.target.value }
                          : entry
                      )),
                    )}
                  />
                  <NativeSelect
                    aria-label="Natural attack damage type"
                    value={attack.damage_type}
                    onChange={(event) => update(
                      'natural_attacks',
                      draft.natural_attacks.map((entry, entryIndex) => (
                        entryIndex === index
                          ? { ...entry, damage_type: event.target.value }
                          : entry
                      )),
                    )}
                  >
                    {['slash', 'pierce', 'blunt', 'fire', 'cold', 'lightning', 'poison', 'necrotic', 'psychic', 'radiant', 'arcane'].map((type) => (
                      <NativeSelectOption key={type} value={type}>
                        {type.charAt(0).toUpperCase() + type.slice(1)}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                  <label className="enemy-natural-range">
                    <span>Range</span>
                    <NativeSelect
                      aria-label="Natural attack range"
                      value={attack.range}
                      onChange={(event) => update(
                        'natural_attacks',
                        draft.natural_attacks.map((entry, entryIndex) => (
                          entryIndex === index
                            ? { ...entry, range: Number(event.target.value) }
                            : entry
                        )),
                      )}
                    >
                      <NativeSelectOption value={0}>Melee · 0</NativeSelectOption>
                      <NativeSelectOption value={1}>Adjacent · 1</NativeSelectOption>
                      <NativeSelectOption value={2}>Near · 2</NativeSelectOption>
                      <NativeSelectOption value={3}>Far · 3</NativeSelectOption>
                      <NativeSelectOption value={4}>Distant · 4</NativeSelectOption>
                    </NativeSelect>
                  </label>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => update(
                      'natural_attacks',
                      draft.natural_attacks.filter((_, entryIndex) => entryIndex !== index),
                    )}
                  >
                    Remove
                  </Button>
                </div>
              ))}
            </div>
          </EnemyEditorSection>

          <EnemyEditorSection title="Behaviour">
            <label className="dialog-label">Typical behaviour
              <Textarea value={draft.typical_behaviour} onChange={(event) => update('typical_behaviour', event.target.value)} />
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
