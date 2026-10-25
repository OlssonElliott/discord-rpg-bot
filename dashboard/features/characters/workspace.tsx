'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Coins,
  ImageIcon,
  Package,
  Plus,
  RefreshCw,
  Save,
  Settings,
  Shield,
  Trash2,
  Upload,
  Users,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import {
  api,
  apiAssetUrl,
  uploadCharacterPortrait,
  type AreaGraphData,
  type AreaSummary,
  type CatalogItem,
  type CharacterAdminData,
  type CharacterStatus,
  type CharacterSummary,
  type EquipmentSlotValue,
} from '@/lib/api';

const ATTRIBUTES = [
  'Strength',
  'Dexterity',
  'Arcana',
  'Vitality',
  'Insight',
  'Personality',
] as const;

const EQUIPMENT_SLOTS: { value: EquipmentSlotValue; label: string }[] = [
  { value: 'main_hand', label: 'Main hand' },
  { value: 'off_hand', label: 'Off hand' },
  { value: 'clothing', label: 'Clothing' },
  { value: 'armor', label: 'Armor' },
  { value: 'container', label: 'Container' },
];

type RoomOption = {
  id: string;
  name: string;
  areaName: string;
};

type CharacterDraft = {
  name: string;
  hp: number;
  maxHp: number;
  status: CharacterStatus;
  failedDeathSaves: number;
  stance: 'steady' | 'bad_stance' | 'prone';
  race: string;
  lineage: string;
  age: string;
  gender: string;
  currentRoomId: string;
  attributes: Record<string, number>;
  skills: Record<string, number>;
  wallet: {
    copper: number;
    silver: number;
    gold: number;
  };
};

type CharacterWorkspaceProps = {
  characters: CharacterSummary[];
  catalogItems: CatalogItem[];
  areas: AreaSummary[];
  onCharactersChanged: () => Promise<void>;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
};

function label(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function draftFrom(character: CharacterAdminData): CharacterDraft {
  return {
    name: character.name,
    hp: character.hp,
    maxHp: character.max_hp,
    status: character.status,
    failedDeathSaves: character.failed_death_saves,
    stance: character.stance,
    race: character.race || '',
    lineage: character.lineage || '',
    age: character.age || '',
    gender: character.gender || '',
    currentRoomId: character.current_room_id || '',
    attributes: Object.fromEntries(
      ATTRIBUTES.map((attribute) => [
        attribute,
        character.attributes[attribute] ?? 10,
      ]),
    ),
    skills: { ...character.skills },
    wallet: { ...character.wallet },
  };
}

function statusForHp(
  persisted: CharacterAdminData,
  currentStatus: CharacterStatus,
  hp: number,
  maxHp: number,
): CharacterStatus {
  if (hp <= -maxHp) return 'dead';
  if (hp <= 0) return 'downed';
  if (persisted.hp <= 0) return 'recovering';
  if (['downed', 'stable', 'dead'].includes(currentStatus)) return 'active';
  return currentStatus;
}

function TextField({
  title,
  value,
  disabled,
  onChange,
}: {
  title: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {title}
      <Input
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function NumberField({
  title,
  value,
  disabled,
  min,
  max,
  onChange,
}: {
  title: string;
  value: number;
  disabled: boolean;
  min?: number;
  max?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      {title}
      <Input
        type="number"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

export function CharacterWorkspace({
  characters,
  catalogItems,
  areas,
  onCharactersChanged,
  onNotice,
  onError,
}: CharacterWorkspaceProps) {
  const [selectedCharacterId, setSelectedCharacterId] = useState<number | null>(
    characters[0]?.id ?? null,
  );
  const [character, setCharacter] = useState<CharacterAdminData | null>(null);
  const [draft, setDraft] = useState<CharacterDraft | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rooms, setRooms] = useState<RoomOption[]>([]);
  const [newSkill, setNewSkill] = useState('');
  const [newItemId, setNewItemId] = useState('');
  const [newItemQuantity, setNewItemQuantity] = useState(1);

  useEffect(() => {
    if (
      selectedCharacterId !== null
      && characters.some((candidate) => candidate.id === selectedCharacterId)
    ) {
      return;
    }
    setSelectedCharacterId(characters[0]?.id ?? null);
  }, [characters, selectedCharacterId]);

  useEffect(() => {
    let cancelled = false;

    const loadRooms = async () => {
      try {
        const graphs = await Promise.all(
          areas.map((area) => api<AreaGraphData>(`/areas/${area.id}/graph`)),
        );
        if (cancelled) return;
        setRooms(
          graphs.flatMap((graph) =>
            graph.nodes.map((room) => ({
              id: room.id,
              name: room.name,
              areaName: graph.area.name,
            })),
          ),
        );
      } catch (requestError) {
        if (!cancelled) {
          onError(
            requestError instanceof Error
              ? requestError.message
              : 'Could not load character room options.',
          );
        }
      }
    };

    void loadRooms();
    return () => {
      cancelled = true;
    };
  }, [areas, onError]);

  const loadCharacter = useCallback(
    async (characterId: number) => {
      setBusy(true);
      try {
        const loaded = await api<CharacterAdminData>(
          `/characters/${characterId}`,
        );
        setCharacter(loaded);
        setDraft(draftFrom(loaded));
        setEditMode(false);
        onError('');
      } catch (requestError) {
        onError(
          requestError instanceof Error
            ? requestError.message
            : 'Could not load character.',
        );
      } finally {
        setBusy(false);
      }
    },
    [onError],
  );

  useEffect(() => {
    if (selectedCharacterId !== null) {
      void loadCharacter(selectedCharacterId);
    } else {
      setCharacter(null);
      setDraft(null);
    }
  }, [loadCharacter, selectedCharacterId]);

  const applyCharacterResult = useCallback(
    async (updated: CharacterAdminData, message: string) => {
      setCharacter(updated);
      if (!editMode) {
        setDraft(draftFrom(updated));
      }
      await onCharactersChanged();
      onNotice(message);
      onError('');
    },
    [editMode, onCharactersChanged, onError, onNotice],
  );

  const toggleEditMode = () => {
    if (!character) return;
    if (editMode) {
      setDraft(draftFrom(character));
      setEditMode(false);
      return;
    }
    setDraft(draftFrom(character));
    setEditMode(true);
  };

  const updateDraftHp = (nextHp: number) => {
    if (!character || !draft || !Number.isFinite(nextHp)) return;
    const boundedHp = Math.max(-draft.maxHp, Math.min(nextHp, draft.maxHp));
    const status = statusForHp(
      character,
      draft.status,
      boundedHp,
      draft.maxHp,
    );
    setDraft({
      ...draft,
      hp: boundedHp,
      status,
      failedDeathSaves: boundedHp > 0 ? 0 : draft.failedDeathSaves,
    });
  };

  const updateDraftMaxHp = (nextMaxHp: number) => {
    if (!character || !draft || !Number.isFinite(nextMaxHp)) return;
    const maxHp = Math.max(1, Math.trunc(nextMaxHp));
    const hp = Math.max(-maxHp, Math.min(draft.hp, maxHp));
    const status = statusForHp(character, draft.status, hp, maxHp);
    setDraft({
      ...draft,
      maxHp,
      hp,
      status,
      failedDeathSaves: hp > 0 ? 0 : draft.failedDeathSaves,
    });
  };

  const saveCharacter = async () => {
    if (!character || !draft) return;
    setBusy(true);
    try {
      const updated = await api<CharacterAdminData>(
        `/characters/${character.id}`,
        {
          method: 'PATCH',
          body: JSON.stringify({
            name: draft.name,
            hp: draft.hp,
            max_hp: draft.maxHp,
            status: draft.status,
            failed_death_saves: draft.failedDeathSaves,
            stance: draft.stance,
            race: draft.race.trim() || null,
            lineage: draft.lineage.trim() || null,
            age: draft.age.trim() || null,
            gender: draft.gender.trim() || null,
            current_room_id: draft.currentRoomId || null,
            attributes: draft.attributes,
            skills: draft.skills,
            wallet: draft.wallet,
          }),
        },
      );
      setCharacter(updated);
      setDraft(draftFrom(updated));
      setEditMode(false);
      await onCharactersChanged();
      onNotice(`${updated.name} saved`);
      onError('');
    } catch (requestError) {
      onError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not save character.',
      );
    } finally {
      setBusy(false);
    }
  };

  const updateInventoryItem = async (
    item: CharacterAdminData['inventory'][number],
    patch: Record<string, unknown>,
    message: string,
  ) => {
    if (!character) return;
    setBusy(true);
    try {
      const updated = await api<CharacterAdminData>(
        `/characters/${character.id}/items/${item.id}`,
        {
          method: 'PATCH',
          body: JSON.stringify(patch),
        },
      );
      await applyCharacterResult(updated, message);
    } catch (requestError) {
      onError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not update inventory item.',
      );
    } finally {
      setBusy(false);
    }
  };

  const removeInventoryItem = async (
    item: CharacterAdminData['inventory'][number],
  ) => {
    if (!character) return;
    setBusy(true);
    try {
      const updated = await api<CharacterAdminData>(
        `/characters/${character.id}/items/${item.id}`,
        { method: 'DELETE' },
      );
      await applyCharacterResult(updated, `${item.name} removed`);
    } catch (requestError) {
      onError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not remove inventory item.',
      );
    } finally {
      setBusy(false);
    }
  };

  const addInventoryItem = async () => {
    if (!character || !newItemId) return;
    setBusy(true);
    try {
      const updated = await api<CharacterAdminData>(
        `/characters/${character.id}/items`,
        {
          method: 'POST',
          body: JSON.stringify({
            template_id: newItemId,
            quantity: newItemQuantity,
          }),
        },
      );
      setNewItemId('');
      setNewItemQuantity(1);
      await applyCharacterResult(updated, 'Item added');
    } catch (requestError) {
      onError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not add inventory item.',
      );
    } finally {
      setBusy(false);
    }
  };

  const uploadPortrait = async (file: File) => {
    if (!character) return;
    setBusy(true);
    try {
      const updated = await uploadCharacterPortrait<CharacterAdminData>(
        character.id,
        file,
      );
      await applyCharacterResult(updated, 'Portrait updated');
    } catch (requestError) {
      onError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not upload portrait.',
      );
    } finally {
      setBusy(false);
    }
  };

  const addSkill = () => {
    if (!draft) return;
    const skill = newSkill.trim();
    if (!skill) return;
    setDraft({
      ...draft,
      skills: {
        ...draft.skills,
        [skill]: draft.skills[skill] ?? 1,
      },
    });
    setNewSkill('');
  };

  if (!characters.length) {
    return (
      <section className="character-workspace character-workspace--empty">
        <Users size={32} />
        <h2>No characters yet</h2>
        <p>Characters created by players will appear here for the DM.</p>
      </section>
    );
  }

  return (
    <section className="character-workspace">
      <aside className="character-sidebar">
        <div className="character-sidebar__heading">
          <div>
            <p className="kicker">Player characters</p>
            <h2>{characters.length} characters</h2>
          </div>
          <Button
            variant="outline"
            size="icon-sm"
            disabled={busy || selectedCharacterId === null}
            onClick={() => {
              if (selectedCharacterId !== null) {
                void loadCharacter(selectedCharacterId);
              }
            }}
            title="Refresh character"
          >
            <RefreshCw />
          </Button>
        </div>

        <div className="character-list">
          {characters.map((summary) => (
            <button
              key={summary.id}
              type="button"
              className={`character-list-card ${
                summary.id === selectedCharacterId ? 'selected' : ''
              }`}
              onClick={() => setSelectedCharacterId(summary.id)}
            >
              <div
                className="character-list-card__portrait"
                style={
                  summary.portrait_url
                    ? {
                        backgroundImage: `url("${apiAssetUrl(
                          summary.portrait_url,
                        )}")`,
                      }
                    : undefined
                }
              >
                {!summary.portrait_url && <Users size={20} />}
              </div>
              <div className="character-list-card__body">
                <strong>{summary.name}</strong>
                <span>
                  {[summary.race, summary.lineage].filter(Boolean).join(' · ')
                    || 'Unknown race'}
                </span>
                <small>
                  {summary.hp}/{summary.max_hp} HP · Hunger {summary.hunger}/100 · {label(summary.status)}
                </small>
                <small>
                  User {summary.discord_user_id} ·{' '}
                  {summary.current_room_name || 'No location'}
                </small>
              </div>
              {summary.is_active && <Badge variant="outline">Active</Badge>}
            </button>
          ))}
        </div>
      </aside>

      <div className="character-detail">
        {!character || !draft ? (
          <div className="character-detail__empty">
            {busy ? 'Loading character…' : 'Select a character.'}
          </div>
        ) : (
          <>
            <header className="character-detail__header">
              <div
                className="character-portrait"
                style={
                  character.portrait_url
                    ? {
                        backgroundImage: `url("${apiAssetUrl(
                          character.portrait_url,
                        )}")`,
                      }
                    : undefined
                }
              >
                {!character.portrait_url && <ImageIcon size={34} />}
                {editMode && (
                  <label className="character-portrait__upload">
                    <Upload size={14} />
                    Change
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      disabled={busy}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void uploadPortrait(file);
                        event.currentTarget.value = '';
                      }}
                    />
                  </label>
                )}
              </div>

              <div className="character-detail__identity">
                <div className="character-detail__title-row">
                  <div>
                    <p className="kicker">Character #{character.id}</p>
                    <h2>{character.name}</h2>
                  </div>
                  <Button
                    variant={editMode ? 'default' : 'outline'}
                    size="sm"
                    disabled={busy}
                    onClick={toggleEditMode}
                  >
                    <Settings />
                    {editMode ? 'Exit edit mode' : 'DM Edit Mode'}
                  </Button>
                </div>

                <div className="character-detail__badges">
                  <Badge variant="outline">{label(character.status)}</Badge>
                  <Badge variant="outline">
                    {character.hp}/{character.max_hp} HP
                  </Badge>
                  <Badge variant="outline">
                    {character.hunger}/100 Hunger
                  </Badge>
                  <Badge variant="outline">{label(character.stance)}</Badge>
                  {character.is_active && <Badge>Active character</Badge>}
                  {editMode && (
                    <Badge className="character-edit-badge">
                      DM EDIT MODE
                    </Badge>
                  )}
                </div>
                <p>
                  Discord user {character.discord_user_id} ·{' '}
                  {character.current_room_name || 'No current room'}
                </p>
              </div>
            </header>

            <div className="character-detail__content">
              <section className="character-card">
                <div className="character-card__heading">
                  <h3>Overview</h3>
                  {character.death_save_dc !== null && (
                    <span>
                      Death Save DC {character.death_save_dc} · Failures{' '}
                      {character.failed_death_saves}/3
                    </span>
                  )}
                </div>

                <div className="character-form-grid">
                  <TextField
                    title="Name"
                    value={draft.name}
                    disabled={!editMode}
                    onChange={(name) => setDraft({ ...draft, name })}
                  />
                  <TextField
                    title="Race"
                    value={draft.race}
                    disabled={!editMode}
                    onChange={(race) => setDraft({ ...draft, race })}
                  />
                  <TextField
                    title="Lineage"
                    value={draft.lineage}
                    disabled={!editMode}
                    onChange={(lineage) => setDraft({ ...draft, lineage })}
                  />
                  <TextField
                    title="Gender"
                    value={draft.gender}
                    disabled={!editMode}
                    onChange={(gender) => setDraft({ ...draft, gender })}
                  />
                  <TextField
                    title="Age"
                    value={draft.age}
                    disabled={!editMode}
                    onChange={(age) => setDraft({ ...draft, age })}
                  />

                  <label>
                    Current room
                    <NativeSelect
                      value={draft.currentRoomId}
                      disabled={!editMode}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          currentRoomId: event.target.value,
                        })
                      }
                    >
                      <NativeSelectOption value="">No room</NativeSelectOption>
                      {rooms.map((room) => (
                        <NativeSelectOption key={room.id} value={room.id}>
                          {room.areaName} · {room.name}
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                  </label>

                  <NumberField
                    title="HP"
                    value={draft.hp}
                    disabled={!editMode}
                    min={-draft.maxHp}
                    max={draft.maxHp}
                    onChange={updateDraftHp}
                  />
                  <NumberField
                    title="Max HP"
                    value={draft.maxHp}
                    disabled={!editMode}
                    min={1}
                    onChange={updateDraftMaxHp}
                  />

                  <label>
                    Status
                    <NativeSelect
                      value={draft.status}
                      disabled={!editMode}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          status: event.target.value as CharacterStatus,
                        })
                      }
                    >
                      {(
                        [
                          'active',
                          'downed',
                          'stable',
                          'recovering',
                          'dead',
                        ] as CharacterStatus[]
                      ).map((status) => (
                        <NativeSelectOption key={status} value={status}>
                          {label(status)}
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                  </label>

                  <label htmlFor="character-stance">
                    Stance
                    <NativeSelect
                      id="character-stance"
                      value={draft.stance}
                      disabled={!editMode}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          stance: event.target.value as CharacterDraft['stance'],
                        })
                      }
                    >
                      <NativeSelectOption value="steady">Steady</NativeSelectOption>
                      <NativeSelectOption value="bad_stance">
                        Bad Stance
                      </NativeSelectOption>
                      <NativeSelectOption value="prone">Prone</NativeSelectOption>
                    </NativeSelect>
                  </label>

                  <NumberField
                    title="Failed death saves"
                    value={draft.failedDeathSaves}
                    disabled={!editMode}
                    min={0}
                    max={3}
                    onChange={(failedDeathSaves) =>
                      setDraft({ ...draft, failedDeathSaves })
                    }
                  />
                </div>
              </section>

              <section className="character-card">
                <div className="character-card__heading">
                  <h3>Attributes</h3>
                  <Shield size={16} />
                </div>
                <div className="character-stat-grid">
                  {ATTRIBUTES.map((attribute) => (
                    <NumberField
                      key={attribute}
                      title={attribute}
                      value={draft.attributes[attribute] ?? 10}
                      disabled={!editMode}
                      onChange={(value) =>
                        setDraft({
                          ...draft,
                          attributes: {
                            ...draft.attributes,
                            [attribute]: value,
                          },
                        })
                      }
                    />
                  ))}
                </div>
              </section>

              <section className="character-card">
                <div className="character-card__heading">
                  <h3>Skills</h3>
                  <span>{Object.keys(draft.skills).length} trained</span>
                </div>

                <div className="character-skill-list">
                  {Object.entries(draft.skills)
                    .sort(([left], [right]) => left.localeCompare(right))
                    .map(([skill, rank]) => (
                      <div className="character-skill-row" key={skill}>
                        <span>{skill}</span>
                        <Input
                          type="number"
                          min={0}
                          value={rank}
                          disabled={!editMode}
                          onChange={(event) =>
                            setDraft({
                              ...draft,
                              skills: {
                                ...draft.skills,
                                [skill]: Number(event.target.value),
                              },
                            })
                          }
                        />
                        {editMode && (
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => {
                              const skills = { ...draft.skills };
                              delete skills[skill];
                              setDraft({ ...draft, skills });
                            }}
                          >
                            <Trash2 />
                          </Button>
                        )}
                      </div>
                    ))}
                  {!Object.keys(draft.skills).length && (
                    <p className="character-muted">No trained skills.</p>
                  )}
                </div>

                {editMode && (
                  <div className="character-inline-add">
                    <Input
                      placeholder="Skill name"
                      value={newSkill}
                      onChange={(event) => setNewSkill(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault();
                          addSkill();
                        }
                      }}
                    />
                    <Button variant="outline" onClick={addSkill}>
                      <Plus /> Add skill
                    </Button>
                  </div>
                )}
              </section>

              <section className="character-card">
                <div className="character-card__heading">
                  <h3>Equipment</h3>
                  <Shield size={16} />
                </div>
                <div className="character-equipment-grid">
                  {EQUIPMENT_SLOTS.map((slot) => {
                    const equipped = character.equipment.find(
                      (item) => item.slot === slot.value,
                    );
                    return (
                      <div key={slot.value}>
                        <span>{slot.label}</span>
                        <strong>{equipped?.name || 'Empty'}</strong>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className="character-card character-card--wide">
                <div className="character-card__heading">
                  <h3>Inventory</h3>
                  <Package size={16} />
                </div>

                <div className="character-inventory-list">
                  {character.inventory.map((item) => (
                    <div className="character-inventory-row" key={item.id}>
                      <div>
                        <strong>{item.name}</strong>
                        <small>{item.template_id}</small>
                      </div>

                      <label htmlFor={`character-item-qty-${item.id}`}>
                        Qty
                        <Input
                          id={`character-item-qty-${item.id}`}
                          type="number"
                          min={0}
                          defaultValue={item.quantity}
                          disabled={!editMode || busy}
                          onBlur={(event) => {
                            const quantity = Number(event.currentTarget.value);
                            if (
                              Number.isInteger(quantity)
                              && quantity !== item.quantity
                            ) {
                              void updateInventoryItem(
                                item,
                                { quantity },
                                `${item.name} quantity updated`,
                              );
                            }
                          }}
                        />
                      </label>

                      <label htmlFor={`character-item-durability-${item.id}`}>
                        Durability
                        <Input
                          id={`character-item-durability-${item.id}`}
                          type="number"
                          min={0}
                          defaultValue={item.durability ?? ''}
                          placeholder="—"
                          disabled={!editMode || busy}
                          onBlur={(event) => {
                            const raw = event.currentTarget.value.trim();
                            const durability =
                              raw === '' ? null : Number(raw);
                            if (
                              (durability === null
                                || Number.isInteger(durability))
                              && durability !== item.durability
                            ) {
                              void updateInventoryItem(
                                item,
                                { durability },
                                `${item.name} durability updated`,
                              );
                            }
                          }}
                        />
                      </label>

                      <label>
                        Slot
                        <NativeSelect
                          value={item.equipped_slot || ''}
                          disabled={!editMode || busy}
                          onChange={(event) =>
                            void updateInventoryItem(
                              item,
                              {
                                equipped_slot:
                                  event.target.value || null,
                              },
                              `${item.name} equipment updated`,
                            )
                          }
                        >
                          <NativeSelectOption value="">
                            Not equipped
                          </NativeSelectOption>
                          {EQUIPMENT_SLOTS.map((slot) => (
                            <NativeSelectOption
                              key={slot.value}
                              value={slot.value}
                            >
                              {slot.label}
                            </NativeSelectOption>
                          ))}
                        </NativeSelect>
                      </label>

                      {editMode && (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          disabled={busy}
                          className="character-inventory-row__remove"
                          onClick={() => void removeInventoryItem(item)}
                        >
                          <Trash2 />
                        </Button>
                      )}
                    </div>
                  ))}

                  {!character.inventory.length && (
                    <p className="character-muted">Inventory is empty.</p>
                  )}
                </div>

                {editMode && (
                  <div className="character-inventory-add">
                    <NativeSelect
                      value={newItemId}
                      onChange={(event) => setNewItemId(event.target.value)}
                    >
                      <NativeSelectOption value="">
                        Choose item…
                      </NativeSelectOption>
                      {catalogItems.map((item) => (
                        <NativeSelectOption key={item.id} value={item.id}>
                          {item.name}
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                    <Input
                      type="number"
                      min={1}
                      value={newItemQuantity}
                      onChange={(event) =>
                        setNewItemQuantity(
                          Math.max(1, Number(event.target.value) || 1),
                        )
                      }
                    />
                    <Button
                      variant="outline"
                      disabled={!newItemId || busy}
                      onClick={() => void addInventoryItem()}
                    >
                      <Plus /> Add item
                    </Button>
                  </div>
                )}
              </section>

              <section className="character-card">
                <div className="character-card__heading">
                  <h3>Wallet</h3>
                  <Coins size={16} />
                </div>
                <div className="character-stat-grid character-wallet">
                  {(['copper', 'silver', 'gold'] as const).map((coin) => (
                    <NumberField
                      key={coin}
                      title={label(coin)}
                      value={draft.wallet[coin]}
                      disabled={!editMode}
                      min={0}
                      onChange={(value) =>
                        setDraft({
                          ...draft,
                          wallet: {
                            ...draft.wallet,
                            [coin]: value,
                          },
                        })
                      }
                    />
                  ))}
                </div>
              </section>
            </div>

            {editMode && (
              <footer className="character-edit-footer">
                <div>
                  <strong>DM Edit Mode</strong>
                  <span>
                    Profile changes apply on Save. Inventory and portrait actions
                    apply immediately.
                  </span>
                </div>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={toggleEditMode}
                >
                  Cancel
                </Button>
                <Button disabled={busy} onClick={() => void saveCharacter()}>
                  <Save /> Save character
                </Button>
              </footer>
            )}
          </>
        )}
      </div>
    </section>
  );
}
