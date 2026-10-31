# AI-RPG — Idea Backlog

A living place to capture ideas **as they arise during development**.

This document is for possibilities, experiments, design questions and "what if"
ideas. **Being listed here does not mean a feature is approved or scheduled.**
We can discuss an idea in chat, add it here, and return to implementing the
current milestone without losing the thought.

See [END_GOAL.md](END_GOAL.md) for the overarching product vision.
Use GitHub Issues/PRs for work that has an agreed scope and is ready to build.

## How we use this document

1. Add an idea as soon as it comes up, even if it is incomplete.
2. Keep the motivation, possible mechanics and unresolved questions together.
3. Mark its status without treating a tentative design as a final game rule.
4. When we decide to build something, create a scoped issue and link it here.
5. Keep the original idea or add an outcome note so we retain the reasoning.

**Statuses:** `Idea` (captured), `Exploring` (discussion/design),
`Planned` (agreed direction), `In progress`, `Implemented`, `Parked`,
`Rejected`.

New ideas can use the next `IDEA-###` number.

## Quick index

| ID | Idea | Area | Status |
| --- | --- | --- | --- |
| IDEA-001 | Take Cover / Leave Cover as distinct actions | Combat | Exploring |
| IDEA-002 | Cover capacity and occupied slots | Combat | Exploring |
| IDEA-003 | Destructible cover with shared HP | Combat / World | Idea |
| IDEA-004 | Material properties and damage types | Combat / World | Idea |
| IDEA-005 | Structural consequences when the environment is destroyed | Combat / World | Idea |
| IDEA-006 | Reusable location-based combat layouts per room | DM Dashboard / World | Exploring |
| IDEA-007 | Player-facing visual location map in Discord | Discord / Combat | Exploring |
| IDEA-008 | Destructible cover sections with individual HP | Combat / World | Parked |

---

## IDEA-001 — Take Cover / Leave Cover

**Added:** 2026-10-25  
**Status:** Exploring  
**Area:** Combat actions

**Idea:** Keep `Move` for changing locations. If the current location offers
cover, `Take Cover` lets the combatant occupy an available cover position
without pretending they moved to another location. `Leave Cover` releases it.

**Why:** A Move menu should not list the location the character is already
standing at as a new travel destination merely because another stance exists.

**Open questions:**
- Does taking/leaving cover consume movement, an action, or something else?
- How should cover interact with attack range and line of sight?
- Should DM be able to override cover positioning?

## IDEA-002 — Cover capacity and occupied slots

**Added:** 2026-10-25  
**Status:** Exploring  
**Area:** Combat state / DM Dashboard

**Idea:** Give cover objects a configurable number of cover slots. For example,
a small crate might protect one combatant, while a large barricade could
protect several. Players and enemies compete for those slots.

**Important distinction:** A location may hold more combatants than the cover
at that location can protect. **Location capacity and cover capacity are
different concepts.**

**Possible behavior:** Occupying cover uses one slot. Leaving the cover or
losing it to destruction frees the slot. Both Discord and DM Dashboard
should reflect occupancy from the same authoritative combat state.

**Open questions:**
- Does each slot have a specific facing/side, or is it abstract initially?
- How are occupants handled if capacity drops while cover is damaged?

## IDEA-003 — Destructible cover objects

**Added:** 2026-10-25  
**Status:** Idea  
**Area:** Combat / dynamic world

**Idea:** Treat cover as a physical **cover object**, not just a defense bonus.
The object could have maximum/current HP, damage reduction, and an intact or
destroyed state.

**First-pass design:** One cover object can provide multiple cover slots but
share **one HP pool**. A hit that damages the object weakens it for everyone
using its cover. At zero HP its protection disappears and occupants lose their
cover benefit.

**Consider later:** Damaged and destroyed visuals, rubble, and the effect of
breaking cover on routes. Do not assume every attack against a protected
combatant automatically damages the cover.

**Open questions:**
- When does an attack hit the character, cover, or both?
- Do cover HP reset for new combats, persist in the world, or depend on the
  object's configuration?
- Does cover degrade in stages before it is completely destroyed?

## IDEA-004 — Material, resistances and immunities

**Added:** 2026-10-25  
**Status:** Idea  
**Area:** Damage system / environment

**Idea:** Cover objects can have material-dependent interactions with damage
types. Examples to explore: wooden barriers affected by fire, stone resisting
many mundane attacks, or a magical barrier reacting differently to spells.

Potential properties:
- Flat damage reduction (DR).
- Resistance or vulnerability to specific damage types.
- Immunity to damage types that cannot plausibly harm the material.
- Optional ongoing effects such as burning.

**Open questions:**
- How do single-target spells, area effects and penetrating attacks interact
  with cover?
- Which rules already exist in the damage engine and should be reused?
- Which materials and values make sense after combat balance testing?

Do **not** finalize a material table or damage formula here prematurely.

## IDEA-005 — Structural links and environmental consequences

**Added:** 2026-10-25  
**Status:** Idea  
**Area:** World / combat / room design

**Idea:** Some cover objects are also parts of the **room's structure**. A
supporting pillar could be explicitly linked to a ceiling section. Destroying
the pillar might cause a partial ceiling collapse, falling debris, damage to
nearby combatants, a newly blocked connection, or rubble that offers new cover.

Other possible relationships:
- Destroy a barricade to open a previously blocked route.
- Collapse a wall to block a connection or reveal another location.
- Destroy supports to change the environment during an encounter.

**Design direction:** The DM authors meaningful structural links and possible
consequences. The game engine resolves the actual effects. We do **not** need
a realistic structural physics simulation.

**Open questions:**
- Which consequences are automatic, and which require DM approval?
- How are consequences represented as game events for Discord and Dashboard?
- Do changes persist after the encounter ends?
- Can destruction produce chain reactions, and if so, how are they bounded?

**Scope:** Save this for a later phase. It is not needed to finish basic
location-based movement.

## IDEA-006 — Reusable combat layouts per room

**Added:** 2026-10-25  
**Status:** Exploring  
**Area:** DM Dashboard / room model

**Idea:** A room can have a reusable graph of combat locations and connections.
DM edits it in a node-based view similar to the existing dungeon room graph.

Reuse permanent room features (doors, pillars, statues, fireplaces) where
possible instead of defining the same room twice. The active combat contains
combatants, temporary effects, occupancy and other mutable encounter state.

**Open questions:**
- Which parts belong to the permanent room and which belong to the encounter?
- What happens to the saved layout if DM changes the room during a combat?
- How do we store or reset persistent environmental destruction?

## IDEA-007 — Visual location-based combat map in Discord

**Added:** 2026-10-25  
**Status:** Exploring  
**Area:** Discord / combat presentation

**Idea:** Show the room as named connected **locations**, a simplified tile-like
system rather than a square grid. Players see their own and known enemy
positions and can interact with locations. DM retains detailed connection,
distance, cost and hazard controls in Dashboard.

**Important:** The existing graph and CombatService are the source of truth.
The player-facing map is a visualization of that same data, **not a second
combat simulation**.

**Current direction:** Finish the Discord Move interaction first, then build
the visual representation. Avoid filling public Discord messages with raw
landmark coordinates and long route lists.

**Open questions:**
- Node-style schematic first, illustrated locations later, or both?
- How does visibility/fog of war apply to combat locations?
- How should larger rooms and partial movement between locations be shown?

## IDEA-008 — Individually destructible cover sections

**Added:** 2026-10-25  
**Status:** Parked  
**Area:** Combat environment

**Idea:** Some objects, such as a barricade made of separate panels, might
have several independently damageable cover sections, each with its own HP.

**Why parked:** A shared cover-object HP pool plus configurable slot capacity
is much simpler as a first implementation. Consider sectional destruction
only when a real gameplay scenario benefits from it.

---

## Template for a new idea

Copy this block when adding another thought:

```md
## IDEA-### — Short descriptive title

**Added:** YYYY-MM-DD
**Status:** Idea
**Area:** Combat / Discord / DM Dashboard / World / Visuals / Other

**Idea:** What could we build?

**Why:** What would make this useful or interesting?

**Possible behavior:** A short example or provisional mechanic.

**Open questions:**
- What still needs to be decided?

**Links:** Related discussion, GitHub issue or PR (optional).
```

When an idea becomes actionable, keep the entry here and link to the
implementation issue or PR rather than erasing the design history.
