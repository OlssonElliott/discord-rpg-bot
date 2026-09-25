import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { CombatantInspectData } from '@/lib/api';

function label(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function CombatantInspectDialog({
  open,
  data,
  loading,
  error,
  onOpenChange,
}: {
  open: boolean;
  data: CombatantInspectData | null;
  loading: boolean;
  error: string;
  onOpenChange: (open: boolean) => void;
}) {
  const hpLabel = (
    data?.hp == null || data.max_hp == null
      ? 'HP unknown'
      : `${data.hp} / ${data.max_hp} HP`
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="combat-inspect-dialog sm:max-w-[760px]">
        <DialogHeader>
          <DialogTitle>{data?.name || 'Combatant inspector'}</DialogTitle>
          <DialogDescription>
            Read-only combat reference for stats, equipment and inventory.
          </DialogDescription>
        </DialogHeader>

        {loading && <p className="combat-inspect-loading">Loading combatant…</p>}
        {error && <p className="combat-inspect-error">{error}</p>}

        {data && !loading && (
          <div className="combat-inspect-content">
            <div className="combat-inspect-summary">
              <div>
                <small>{data.kind}</small>
                <strong>{hpLabel}</strong>
              </div>
              <Badge variant="outline">{label(data.status)}</Badge>
              {data.failed_death_saves != null && data.failed_death_saves > 0 && (
                <Badge variant="outline">
                  Death saves {data.failed_death_saves}/3
                </Badge>
              )}
              {data.death_save_dc != null && (
                <Badge variant="outline">Death Save DC {data.death_save_dc}</Badge>
              )}
              {data.stance && <Badge variant="outline">{label(data.stance)}</Badge>}
              {data.race && <Badge variant="outline">{data.race}</Badge>}
            </div>

            {data.status === 'recovering' && (
              <p className="combat-inspect-description">
                Recovering: active d20 rolls are made with disadvantage until a Short Rest.
              </p>
            )}

            {data.description && (
              <p className="combat-inspect-description">{data.description}</p>
            )}

            <section className="combat-inspect-section">
              <h3>Attributes</h3>
              <div className="combat-inspect-stats">
                {Object.entries(data.attributes).map(([name, value]) => (
                  <div key={name}>
                    <small>{label(name)}</small>
                    <strong>{value}</strong>
                  </div>
                ))}
                {!Object.keys(data.attributes).length && (
                  <p className="muted-row">No structured attributes available.</p>
                )}
              </div>
            </section>

            {data.enemy && (
              <section className="combat-inspect-section">
                <h3>Combat profile</h3>
                <div className="combat-inspect-stats">
                  <div><small>Difficulty</small><strong>{data.enemy.difficulty_level}</strong></div>
                  <div><small>Armor</small><strong>{data.enemy.armor}</strong></div>
                  <div><small>Magic resistance</small><strong>{data.enemy.magical_resistance}</strong></div>
                  <div><small>Attack DC</small><strong>{data.enemy.attack_dc}</strong></div>
                  <div><small>Defense DC</small><strong>{data.enemy.defense_dc}</strong></div>
                  <div><small>Damage</small><strong>{data.enemy.damage}</strong></div>
                </div>
                <dl className="combat-inspect-details">
                  <div><dt>Attack profile</dt><dd>{data.enemy.attack_profile}</dd></div>
                  {data.enemy.special_ability && (
                    <div><dt>Special ability</dt><dd>{data.enemy.special_ability}</dd></div>
                  )}
                  <div><dt>Typical behaviour</dt><dd>{data.enemy.typical_behaviour}</dd></div>
                </dl>
              </section>
            )}

            {!!Object.keys(data.skills).length && (
              <section className="combat-inspect-section">
                <h3>Skills</h3>
                <div className="combat-inspect-stats">
                  {Object.entries(data.skills).map(([name, value]) => (
                    <div key={name}>
                      <small>{label(name)}</small>
                      <strong>{value}</strong>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="combat-inspect-section">
              <h3>Equipment</h3>
              <div className="combat-inspect-list">
                {data.equipment.map((item) => (
                  <div key={`${item.slot}:${item.id}`}>
                    <span>
                      <small>{label(item.slot || '')}</small>
                      <strong>{item.name}</strong>
                    </span>
                  </div>
                ))}
                {!data.equipment.length && <p className="muted-row">Nothing equipped.</p>}
              </div>
            </section>

            <section className="combat-inspect-section">
              <h3>Inventory</h3>
              <div className="combat-inspect-list">
                {data.inventory.map((item) => (
                  <div key={item.id}>
                    <span>
                      <strong>{item.name}</strong>
                      {item.equipped_slot && <small>{label(item.equipped_slot)}</small>}
                    </span>
                    <Badge variant="outline">×{item.quantity ?? 1}</Badge>
                  </div>
                ))}
                {!data.inventory.length && <p className="muted-row">Inventory is empty.</p>}
              </div>
            </section>

            {data.wallet && (
              <section className="combat-inspect-wallet">
                <span>{data.wallet.copper} copper</span>
                <span>{data.wallet.silver} silver</span>
                <span>{data.wallet.gold} gold</span>
              </section>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
