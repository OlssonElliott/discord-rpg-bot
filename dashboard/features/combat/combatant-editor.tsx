'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, CircleAlert, Eye, MoveRight, Shield, Skull, Swords, Trash2, Users } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  NativeSelect,
  NativeSelectOptGroup,
  NativeSelectOption,
} from '@/components/ui/native-select';
import type { CombatSceneData, CombatantData } from '@/lib/api';

type Relation = CombatantData['relation'];

function label(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function sameCombatPosition(
  first: CombatantData,
  second: CombatantData,
) {
  if (first.is_between_landmarks !== second.is_between_landmarks) return false;
  if (!first.is_between_landmarks) {
    return first.landmark_id === second.landmark_id;
  }

  const firstRoute = [
    first.route_source_landmark_id,
    first.route_destination_landmark_id,
  ].sort().join('::');
  const secondRoute = [
    second.route_source_landmark_id,
    second.route_destination_landmark_id,
  ].sort().join('::');
  if (firstRoute !== secondRoute || first.route_cost !== second.route_cost) {
    return false;
  }

  const canonicalStart = [
    first.route_source_landmark_id || '',
    first.route_destination_landmark_id || '',
  ].sort()[0];
  const firstProgress = first.route_source_landmark_id === canonicalStart
    ? first.route_progress
    : first.route_cost - first.route_progress;
  const secondProgress = second.route_source_landmark_id === canonicalStart
    ? second.route_progress
    : second.route_cost - second.route_progress;
  return firstProgress === secondProgress;
}

export function CombatantEditor({
  combatant,
  scene,
  busy,
  selected,
  onMove,
  onMoveTowardCombatant,
  onInspect,
  onRemoveEnemy,
  onAttack,
  onDefend,
  onDash,
  onUseItem,
  onSetInitiative,
}: {
  combatant: CombatantData;
  scene: CombatSceneData;
  busy: boolean;
  selected: boolean;
  onMove: (
    combatant: CombatantData,
    landmarkId: string,
    relation: Relation,
  ) => Promise<boolean>;
  onMoveTowardCombatant: (
    combatant: CombatantData,
    target: CombatantData,
  ) => Promise<boolean>;
  onInspect: (combatant: CombatantData) => void;
  onRemoveEnemy: (enemyId: string) => Promise<boolean>;
  onAttack: (
    attacker: CombatantData,
    targetId: string,
  ) => Promise<boolean>;
  onDefend: () => Promise<boolean>;
  onDash: () => Promise<boolean>;
  onUseItem: (itemInstanceId: string) => Promise<boolean>;
  onSetInitiative: (
    combatant: CombatantData,
    initiativeScore: number,
  ) => Promise<boolean>;
}) {
  const [movementTarget, setMovementTarget] = useState('');
  const [relation, setRelation] = useState<Relation>(combatant.relation);
  const [initiativeScore, setInitiativeScore] = useState(combatant.initiative_score);
  const [expanded, setExpanded] = useState(combatant.is_current_turn);
  const wasCurrentTurn = useRef(combatant.is_current_turn);
  const movementTargetLandmarkId = movementTarget.startsWith('landmark:')
    ? movementTarget.slice('landmark:'.length)
    : '';
  const movementLandmark = scene.landmarks.find(
    (landmark) => landmark.id === movementTargetLandmarkId,
  ) ?? null;
  const targetKind = combatant.kind === 'character' ? 'enemy' : 'character';
  const incapacitated = (
    combatant.kind === 'character'
    && ['downed', 'stable', 'dead'].includes(combatant.character_status || '')
  );
  const attackTargets = scene.combatants.filter(
    (candidate) => (
      candidate.kind === targetKind
      && (
        candidate.kind !== 'character'
        || ['active', 'recovering'].includes(candidate.character_status || '')
      )
    ),
  );
  const [attackTargetId, setAttackTargetId] = useState(
    attackTargets[0]?.source_id || '',
  );
  const [attackError, setAttackError] = useState('');
  const [itemInstanceId, setItemInstanceId] = useState(
    combatant.usable_items[0]?.id || '',
  );
  const selectedItem = combatant.usable_items.find(
    (item) => item.id === itemInstanceId,
  );
  const selectedAttackTarget = scene.combatants.find(
    (candidate) => (
      candidate.kind === targetKind
      && candidate.source_id === attackTargetId
    ),
  ) ?? null;

  useEffect(() => {
    setMovementTarget('');
    setRelation(combatant.relation);
    setInitiativeScore(combatant.initiative_score);
  }, [
    combatant.initiative_score,
    combatant.landmark_id,
    combatant.relation,
    combatant.route_destination_landmark_id,
    combatant.route_progress,
  ]);

  useEffect(() => {
    if (combatant.is_current_turn && !wasCurrentTurn.current) {
      setExpanded(true);
    } else if (!combatant.is_current_turn && wasCurrentTurn.current) {
      setExpanded(false);
    }
    wasCurrentTurn.current = combatant.is_current_turn;
  }, [combatant.is_current_turn]);

  useEffect(() => {
    if (selected) {
      setExpanded(true);
    }
  }, [selected]);

  useEffect(() => {
    if (relation === 'behind' && movementLandmark?.cover === 'none') {
      setRelation('at');
    }
  }, [movementLandmark?.cover, relation]);

  useEffect(() => {
    if (
      itemInstanceId
      && combatant.usable_items.some((item) => item.id === itemInstanceId)
    ) {
      return;
    }
    setItemInstanceId(combatant.usable_items[0]?.id || '');
  }, [combatant.usable_items, itemInstanceId]);

  useEffect(() => {
    const validTarget = scene.combatants.some(
      (candidate) => (
        candidate.source_id === attackTargetId
        && candidate.kind === targetKind
        && (
          candidate.kind !== 'character'
          || ['active', 'recovering'].includes(candidate.character_status || '')
        )
      ),
    );
    if (attackTargetId && validTarget) return;

    const firstTarget = scene.combatants.find(
      (candidate) => (
        candidate.kind === targetKind
        && (
          candidate.kind !== 'character'
          || ['active', 'recovering'].includes(candidate.character_status || '')
        )
      ),
    );
    setAttackTargetId(firstTarget?.source_id || '');
  }, [attackTargetId, scene.combatants, targetKind]);

  const routeSource = combatant.route_source_landmark_id
    ? scene.landmarks.find(
      (landmark) => landmark.id === combatant.route_source_landmark_id,
    )
    : null;
  const routeDestination = combatant.route_destination_landmark_id
    ? scene.landmarks.find(
      (landmark) => landmark.id === combatant.route_destination_landmark_id,
    )
    : null;

  const directLandmarkTargets = (() => {
    if (combatant.is_between_landmarks) {
      const targets: Array<{ id: string; cost: number }> = [];
      if (combatant.route_source_landmark_id) {
        targets.push({
          id: combatant.route_source_landmark_id,
          cost: combatant.route_progress,
        });
      }
      if (combatant.route_destination_landmark_id) {
        targets.push({
          id: combatant.route_destination_landmark_id,
          cost: combatant.route_cost - combatant.route_progress,
        });
      }
      return targets;
    }

    return scene.routes
      .filter((route) => (
        !route.blocked
        && (
          route.source_landmark_id === combatant.landmark_id
          || route.destination_landmark_id === combatant.landmark_id
        )
      ))
      .map((route) => ({
        id: route.source_landmark_id === combatant.landmark_id
          ? route.destination_landmark_id
          : route.source_landmark_id,
        cost: route.movement_cost,
      }));
  })();

  const localLandmarkIds = new Set([
    combatant.landmark_id,
    ...directLandmarkTargets.map((target) => target.id),
  ]);

  const localRouteKeys = new Set<string>();
  if (combatant.is_between_landmarks) {
    if (
      combatant.route_source_landmark_id
      && combatant.route_destination_landmark_id
    ) {
      localRouteKeys.add([
        combatant.route_source_landmark_id,
        combatant.route_destination_landmark_id,
      ].sort().join('::'));
    }
  } else {
    for (const route of scene.routes) {
      if (route.blocked) continue;
      if (
        route.source_landmark_id === combatant.landmark_id
        || route.destination_landmark_id === combatant.landmark_id
      ) {
        localRouteKeys.add([
          route.source_landmark_id,
          route.destination_landmark_id,
        ].sort().join('::'));
      }
    }
  }

  const movementCostToCombatant = (target: CombatantData) => {
    if (sameCombatPosition(combatant, target)) return 0;

    if (!target.is_between_landmarks) {
      return directLandmarkTargets.find(
        (candidate) => candidate.id === target.landmark_id,
      )?.cost ?? null;
    }

    const targetRouteKey = [
      target.route_source_landmark_id || '',
      target.route_destination_landmark_id || '',
    ].sort().join('::');
    if (!localRouteKeys.has(targetRouteKey)) return null;

    if (
      combatant.is_between_landmarks
      && [
        combatant.route_source_landmark_id || '',
        combatant.route_destination_landmark_id || '',
      ].sort().join('::') === targetRouteKey
      && combatant.route_cost === target.route_cost
    ) {
      const canonicalStart = [
        combatant.route_source_landmark_id || '',
        combatant.route_destination_landmark_id || '',
      ].sort()[0];
      const combatantProgress = (
        combatant.route_source_landmark_id === canonicalStart
          ? combatant.route_progress
          : combatant.route_cost - combatant.route_progress
      );
      const targetProgress = (
        target.route_source_landmark_id === canonicalStart
          ? target.route_progress
          : target.route_cost - target.route_progress
      );
      return Math.abs(targetProgress - combatantProgress);
    }

    if (!combatant.is_between_landmarks) {
      if (
        target.route_source_landmark_id === combatant.landmark_id
      ) {
        return target.route_progress;
      }
      if (
        target.route_destination_landmark_id === combatant.landmark_id
      ) {
        return target.route_cost - target.route_progress;
      }
    }

    return null;
  };

  const movementCombatantTargets = scene.combatants
    .map((candidate) => ({
      combatant: candidate,
      cost: movementCostToCombatant(candidate),
    }))
    .filter((entry) => (
      !(
        entry.combatant.kind === combatant.kind
        && entry.combatant.source_id === combatant.source_id
      )
      && entry.cost != null
      && entry.cost > 0
    ));

  const selectedMovementCombatant = movementTarget.startsWith('combatant:')
    ? scene.combatants.find(
      (candidate) => (
        `combatant:${candidate.kind}:${candidate.source_id}`
        === movementTarget
      ),
    ) ?? null
    : null;

  return (
    <div
      className={[
        'combatant-editor',
        combatant.is_current_turn ? 'combatant-editor--current' : '',
        selected ? 'combatant-editor--selected' : '',
      ].filter(Boolean).join(' ')}
    >
      <button
        type="button"
        className="combatant-editor__toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((open) => !open)}
      >
        <span className="combatant-editor__name">
          {combatant.kind === 'character' ? <Users size={15} /> : <Skull size={15} />}
          <span>{combatant.name}</span>
          {combatant.is_current_turn && <Badge>Current turn</Badge>}
          {combatant.character_status && (
            <Badge variant="outline">{label(combatant.character_status)}</Badge>
          )}
          {combatant.defending && (
            <Badge variant="outline">Defending</Badge>
          )}
          {combatant.dashed && (
            <Badge variant="outline">Dashed</Badge>
          )}
          {combatant.hp != null && combatant.max_hp != null && (
            <Badge variant="outline">{combatant.hp}/{combatant.max_hp} HP</Badge>
          )}
          {combatant.hunger != null && (
            <Badge variant="outline">{combatant.hunger}/100 Hunger</Badge>
          )}
          <Badge variant="outline">
            Move {combatant.movement_remaining} · Speed {combatant.movement_budget}
          </Badge>
          <Badge variant="outline">Init {combatant.initiative_score}</Badge>
        </span>
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {expanded && (
        <>
      {combatant.character_status === 'downed' && (
        <p className="combatant-editor__condition-state">
          Death Save DC {combatant.death_save_dc ?? 10}
          {' · '}
          Failed {combatant.failed_death_saves ?? 0}/3
          {' · '}
          Death save resolves when this turn begins
        </p>
      )}
      {combatant.character_status === 'stable' && (
        <p className="combatant-editor__condition-state">
          Stable at {combatant.hp} HP · Cannot act until healed above 0 HP
        </p>
      )}
      {combatant.character_status === 'recovering' && (
        <p className="combatant-editor__condition-state">
          Recovering · Disadvantage on active d20 rolls until a Short Rest
        </p>
      )}
      {combatant.is_between_landmarks && (
        <p className="combatant-editor__movement-state">
          Between {routeSource?.name || combatant.route_source_landmark_id}
          {' ↔ '}
          {routeDestination?.name || combatant.route_destination_landmark_id}
          {' · '}
          {combatant.route_progress}/{combatant.route_cost}
        </p>
      )}
      <div className="combatant-editor__movement-control">
        <NativeSelect
          aria-label="Movement target"
          value={movementTarget}
          disabled={
            busy
            || !combatant.is_current_turn
            || incapacitated
            || combatant.movement_remaining <= 0
          }
          onChange={(event) => {
            setMovementTarget(event.target.value);
            setRelation('at');
          }}
        >
          <NativeSelectOption value="">Choose movement target…</NativeSelectOption>
          {directLandmarkTargets.length > 0 && (
            <NativeSelectOptGroup label="Connected landmarks">
              {directLandmarkTargets.map((target) => {
                const landmark = scene.landmarks.find(
                  (candidate) => candidate.id === target.id,
                );
                if (!landmark) return null;
                return (
                  <NativeSelectOption
                    key={target.id}
                    value={`landmark:${target.id}`}
                  >
                    {landmark.name} · Move {target.cost}
                  </NativeSelectOption>
                );
              })}
            </NativeSelectOptGroup>
          )}
          {movementCombatantTargets.length > 0 && (
            <NativeSelectOptGroup label="Combatants">
              {movementCombatantTargets.map(({ combatant: target, cost }) => (
                <NativeSelectOption
                  key={`${target.kind}:${target.source_id}`}
                  value={`combatant:${target.kind}:${target.source_id}`}
                >
                  {target.name} · Move {cost}
                  {target.is_between_landmarks
                    ? ` · path ${target.route_progress}/${target.route_cost}`
                    : ''}
                </NativeSelectOption>
              ))}
            </NativeSelectOptGroup>
          )}
        </NativeSelect>
        {movementLandmark && (
          <NativeSelect
            aria-label="Movement relation"
            value={relation}
            disabled={busy || !combatant.is_current_turn || incapacitated}
            onChange={(event) => setRelation(event.target.value as Relation)}
          >
            <NativeSelectOption value="at">At</NativeSelectOption>
            {movementLandmark.cover !== 'none' && (
              <NativeSelectOption value="behind">Behind</NativeSelectOption>
            )}
          </NativeSelect>
        )}
        <Button
          size="sm"
          variant="outline"
          disabled={
            busy
            || !combatant.is_current_turn
            || incapacitated
            || combatant.movement_remaining <= 0
            || !movementTarget
          }
          onClick={() => {
            if (movementLandmark) {
              void onMove(
                combatant,
                movementLandmark.id,
                relation,
              ).then((ok) => {
                if (ok) setMovementTarget('');
              });
              return;
            }
            if (selectedMovementCombatant) {
              void onMoveTowardCombatant(
                combatant,
                selectedMovementCombatant,
              ).then((ok) => {
                if (ok) setMovementTarget('');
              });
            }
          }}
        >
          <MoveRight /> Move
        </Button>
      </div>
      <div className="combatant-editor__standard-action">
          <div>
            <span>Standard Action</span>
            <Badge
              variant="outline"
              className={
                combatant.standard_action_spent
                  ? 'combat-action-badge--spent'
                  : 'combat-action-badge--ready'
              }
            >
              {combatant.standard_action_spent ? 'Spent' : 'Ready'}
            </Badge>
          </div>
          <NativeSelect
            aria-label="Attack target"
            value={attackTargetId}
            disabled={
              busy
              || !combatant.is_current_turn
              || incapacitated
              || combatant.standard_action_spent
            }
            onChange={(event) => {
              setAttackTargetId(event.target.value);
              setAttackError('');
            }}
          >
            <NativeSelectOption value="">Choose target…</NativeSelectOption>
            {attackTargets.map((target) => (
              <NativeSelectOption
                key={target.source_id}
                value={target.source_id}
              >
                {target.name}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          <Button
            size="sm"
            disabled={
              busy
              || !combatant.is_current_turn
              || incapacitated
              || combatant.standard_action_spent
              || !attackTargetId
            }
            onClick={() => {
              if (
                selectedAttackTarget
                && !sameCombatPosition(combatant, selectedAttackTarget)
              ) {
                setAttackError(
                  `${selectedAttackTarget.name} is not within melee range.`,
                );
                return;
              }
              setAttackError('');
              void onAttack(combatant, attackTargetId).then((ok) => {
                if (ok) setAttackError('');
              });
            }}
          >
            <Swords /> Attack
          </Button>
          {attackError && (
            <p className="combatant-editor__attack-error" role="alert">
              <CircleAlert size={13} />
              {attackError}
            </p>
          )}
          {combatant.kind === 'character' && (
            <Button
              size="sm"
              variant="outline"
              disabled={
                busy
                || !combatant.is_current_turn
                || incapacitated
                || combatant.standard_action_spent
              }
              onClick={() => void onDefend()}
            >
              <Shield /> Defend
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            disabled={
              busy
              || !combatant.is_current_turn
              || incapacitated
              || combatant.standard_action_spent
            }
            onClick={() => void onDash()}
          >
            <MoveRight /> Dash +{combatant.movement_budget}
          </Button>
          {combatant.usable_items.length > 0 && (
            <>
              <NativeSelect
                aria-label="Use item"
                value={itemInstanceId}
                disabled={
                  busy
                  || !combatant.is_current_turn
                  || incapacitated
                  || combatant.standard_action_spent
                }
                onChange={(event) => setItemInstanceId(event.target.value)}
              >
                <NativeSelectOption value="">Choose item…</NativeSelectOption>
                {combatant.usable_items.map((item) => (
                  <NativeSelectOption key={item.id} value={item.id}>
                    {item.name} ×{item.quantity}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
              {selectedItem && (
                <small className="combatant-editor__item-effect">
                  {selectedItem.affected_stat === 'hp'
                    ? `Restores ${selectedItem.affected_amount} HP`
                    : selectedItem.affected_stat === 'hunger'
                      ? `Reduces Hunger by ${selectedItem.affected_amount}`
                      : `Affects ${label(selectedItem.affected_stat)} by ${selectedItem.affected_amount}`}
                </small>
              )}
              <Button
                size="sm"
                variant="outline"
                disabled={
                  busy
                  || !combatant.is_current_turn
                  || incapacitated
                  || combatant.standard_action_spent
                  || !itemInstanceId
                }
                onClick={() => void onUseItem(itemInstanceId)}
              >
                Use Item
              </Button>
            </>
          )}
        </div>
      <div className="combatant-editor__initiative">
        <span>
          Initiative
          <small>d20 {combatant.initiative_roll}</small>
        </span>
        <Input
          type="number"
          value={initiativeScore}
          onChange={(event) => setInitiativeScore(Number(event.target.value))}
        />
        <Button
          size="sm"
          variant="outline"
          disabled={
            busy
            || !Number.isInteger(initiativeScore)
            || initiativeScore === combatant.initiative_score
          }
          onClick={() => void onSetInitiative(combatant, initiativeScore)}
        >
          Set
        </Button>
      </div>
      <div className="combatant-editor__actions">
        <Button
          size="sm"
          variant="outline"
          onClick={() => onInspect(combatant)}
        >
          <Eye /> Inspect
        </Button>
        {combatant.kind === 'enemy' && (
          <Button
            className="combatant-editor__remove"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => void onRemoveEnemy(combatant.source_id)}
          >
            <Trash2 /> Remove
          </Button>
        )}
      </div>
        </>
      )}
    </div>
  );
}
