# AI RPG Discord Game — End Goal

## Vision

The end goal is to build a Discord-native RPG where players do not just read what happens.

They **play an interactive story that turns into a manga/comic while they play it**.

The game should combine:

- free-form roleplay
- deterministic RPG mechanics
- persistent characters and world state
- automated combat bookkeeping
- animated/custom dice
- manga/comic panels and short strips
- sound effects
- character-specific visual identity
- environments that reflect the real game world
- optional motion-comic / anime-like presentation later

The core fantasy is:

> A group plays an RPG together in Discord, and their shared story is continuously visualized as a manga in real time.

This should not feel like “an AI chatbot with pictures”.

It should feel like a real game where Discord is the interface and the story is being visually directed while the players play.

---

# Core Product Identity

A concise description of the project:

> **An interactive RPG that transforms the players' actions into a living manga/comic as they play.**

Or, technically:

> **A state-aware modular comic renderer connected to a deterministic RPG engine.**

The important distinction is that the images are not the source of truth.

The game engine knows what actually happened.

The visual system only decides how to present it.

---

# High-Level Architecture

The project should keep gameplay logic, interpretation, presentation, and rendering separated.

```text
PLAYER INPUT
    ↓
DISCORD
    ↓
INTENT INTERPRETER
    ↓
STRUCTURED INTENT
    ↓
GAME ENGINE / VALIDATOR
    ↓
RESOLVED GAME EVENT
    ↓
VISUAL SNAPSHOT
    ↓
VISUAL DIRECTOR
    ↓
STRIP PLAN
    ↓
ASSET RESOLVER
    ↓
COMPOSITOR / RENDERER
    ↓
COMIC PANEL / STRIP
    ↓
DISCORD
```

The key rule is:

> **Game state defines reality. Visuals represent reality.**

The visual system must never invent or alter mechanical truth.

---

# Discord as the Game Interface

Discord is the frontend/UI layer.

The bot should expose:

- slash commands
- buttons
- select menus
- ephemeral character/inventory panels
- combat messages
- dice animations
- comic strips
- sound/visual feedback
- narrative output

Discord interaction handlers should stay thin.

They should call game/application services rather than contain gameplay rules directly.

Conceptually:

```text
Discord
    ↓
Bot integration / handlers
    ↓
Application services
    ↓
Domain/game logic
    ↓
Persistence
```

Discord is where the player interacts.

The actual RPG rules and state should remain independent from Discord.

---

# Player Characters and Persistent State

Discord users should be linked to persistent game characters.

Character state can include:

- HP
- stats
- skills
- equipment
- inventory
- stance
- conditions
- position
- injuries
- scars
- missing limbs
- visual appearance
- visual asset versions

Character visuals should reflect the actual current state of the character.

If a player equips new boots, armor, weapon, or gains a permanent scar, the visual state should eventually reflect it.

---

# Free-Form Actions Outside Combat

Outside combat, players should be able to write natural actions directly.

Example:

> `I draw my sword.`

The system should not let the language model directly mutate state.

Instead:

```text
"I draw my sword"
    ↓
Intent Interpreter
    ↓
{
  intent: draw_weapon,
  target: equipped_primary_weapon
}
    ↓
Game Validator
    ↓
Weapon state changes
    ↓
Visual event is created
```

The resulting action can immediately create a manga panel or small strip.

Example:

```text
Player:
"I draw my sword."

↓ GAME RESOLVES ACTION

[close-up: hand pulling sword from sheath]

SHHKK
```

The environment should match the current location where possible.

The same principle applies to actions such as:

- open a door
- light a torch
- inspect a corpse
- kneel
- sit down
- pick up an item
- drink a potion
- hand an NPC something
- point at something
- threaten someone
- bow
- step closer
- examine an object
- push something
- climb
- interact with scenery

The goal is that normal roleplay can become visual without requiring explicit image-generation commands.

---

# NPC Interaction

NPC interactions should also be presented as small manga beats.

They do not need full two-character scenes every time.

For example:

```text
Player hands over papers
    ↓

Panel 1:
close-up of player's hand holding papers

Panel 2:
guard's hand taking them
```

Dialogue scenes can use:

- face closeups
- eyes
- profile shots
- torso shots
- hands
- body language
- reaction shots
- environment details
- meaningful objects

This is especially useful because manga often implies interaction through editing rather than showing every participant in every panel.

---

# Visual Pacing Outside Combat

Not every player message needs an image.

The system should decide whether a visual adds value.

Possible presentation levels:

## No panel

Use text only for trivial or repetitive moments.

## Single panel

Default for simple meaningful actions.

Examples:

- draw weapon
- open door
- light torch
- inspect object
- hand over money
- drink potion

## Mini-strip

Usually 2–3 panels.

Use for:

- important NPC introductions
- emotional reactions
- discoveries
- threats
- dramatic reveals
- major environment interactions

The goal is visual rhythm rather than image spam.

---

# Combat Presentation

Combat remains mechanically deterministic.

The game engine resolves:

- attack rolls
- saves
- damage
- armor/resistance
- HP
- stances
- openings
- prone states
- movement
- positions
- enemy state
- death
- other mechanical outcomes

Only after the combat result exists should the visual system decide how to show it.

Example:

```text
AttackResolved

attacker: Olof
weapon: Great Axe
result: hit
damage: 12
target stance:
    steady → bad_stance
```

The Visual Director might convert that to:

```text
Panel 1
attacker close-up
focused expression

Panel 2
heavy overhead attack
speed lines

Panel 3
target staggering backward
heavy impact FX
```

The image never decides that the target became off-balance.

The combat engine already decided it.

---

# One Character Per Panel in V1

The first version should strongly prefer:

> **Maximum one clearly visible active character per panel.**

This dramatically reduces visual complexity.

A fight does not require both characters in the same image.

Example:

```text
Panel 1
attacker winds up

Panel 2
attacker swings

Panel 3
defender reacts
```

This still reads naturally as one continuous action.

Benefits:

- easier consistency
- easier equipment compositing
- easier character generation
- fewer body-interaction errors
- no need for precise weapon collision
- easier camera reuse
- easier environment integration
- simpler asset library

The underlying data model should still allow multiple subjects later.

V1 can enforce the limit through presentation policy rather than hardcoding the data model around one character forever.

---

# Typical Strip Length

Most actions should use:

> **1–3 panels**

Examples:

Simple action:

```text
[draw sword]
```

Normal hit:

```text
[attack] → [reaction]
```

Dramatic hit:

```text
[face close-up] → [attack] → [heavy reaction]
```

The game should not try to illustrate every millisecond of an action.

It should select the visually important beats.

---

# Manga as a Visual Grammar

The system should think in visual beats rather than complete cinematic scenes.

Reusable concepts include:

```text
SLASH
THRUST
OVERHEAD ATTACK
BLOCK
DODGE
CAST
RUN
KNEEL
INSPECT
DRAW WEAPON
OPEN
REACH
HIT LIGHT
HIT HEAVY
STAGGER
FALL
PRONE
DEATH
REACTION
FACE CLOSE-UP
OBJECT CLOSE-UP
```

Manga naturally supports:

- speed lines
- extreme crops
- silhouettes
- closeups
- reaction frames
- impact frames
- abstract backgrounds
- object focus
- implied off-screen action

This is an advantage.

The system does not need to render the whole battlefield for every action.

It only needs to show enough for the player to understand and feel the moment.

---

# Pose Library

The reusable pose library should be built from neutral pose templates rather than finished characters.

A pose should represent geometry, not identity.

A pose can contain:

- skeleton/joint positions
- torso orientation
- arm positions
- hand positions
- leg positions
- facing direction
- camera/view
- ground contact
- weapon anchors
- recommended crops
- compatible grip types
- mirroring safety

The pose itself should not contain:

- a specific face
- hair
- armor
- character identity
- permanent weapon art
- unique clothing

Conceptually:

```text
POSE
    ↓
CHARACTER BODY
    ↓
FACE / HAIR
    ↓
CLOTHING
    ↓
ARMOR
    ↓
WEAPON
    ↓
FX
```

This allows a relatively small pose library to serve the whole party and many humanoid enemies.

---

# Why a Small Pose Library Can Go Far

A pose is only one dimension of variation.

A single pose can be combined with:

- different characters
- different body appearances
- different weapons
- different equipment
- different expressions
- different environments
- different crops
- different camera framing
- different FX
- different panel layouts
- different sound effects

Conceptually:

```text
30 poses
× characters
× weapons
× environments
× crops
× expressions
× FX
```

The perceived variety becomes much larger than the number of base poses.

Players are also unlikely to notice repeated body geometry when:

- the character is different
- the equipment is different
- the weapon is different
- the environment is different
- the crop is different
- the scene context is different

---

# Rig Profiles

Avoid making separate pose libraries for every race/gender combination unless necessary.

Prefer reusable rig profiles such as:

```text
humanoid_small
humanoid_medium
humanoid_large
quadruped_medium
```

A human, elf, bandit, cultist, or similar humanoid may share the same rig profile.

Identity and appearance are layered on top.

This reduces asset explosion.

---

# Equipment as Modular Assets

Equipment should be treated as reusable visual assets.

Examples:

- weapons
- helmets
- chest armor
- gloves
- boots
- shields
- cloaks
- accessories

The same weapon asset should be usable by different characters.

The ideal long-term system is modular:

```text
base body
+ face
+ hair
+ chest armor
+ gloves
+ boots
+ weapon
+ accessories
```

Where practical, equipment should use:

- transparent layers
- anchor points
- masks
- z-order metadata
- pose compatibility
- rig compatibility

Weapons are particularly suitable as independently anchored assets.

Clothing and armor may require pose-specific variants or deformation/rigging later.

---

# Character Visual Identity

Character identity should be separated from current appearance.

## Canonical Identity

Stable information such as:

- face
- hair baseline
- skin
- body shape
- height
- permanent features

This should be treated as the source reference.

## Body State

Persistent/semi-persistent changes such as:

- scars
- missing limbs
- tattoos
- burns
- major wounds

## Equipment State

Current wearable/held items.

## Transient Scene State

Temporary appearance such as:

- blood
- dirt
- wet clothing
- poison effect
- expression
- temporary stance

Permanent changes should update the character's reusable visual assets.

Transient changes should usually be scene instructions.

Avoid repeatedly generating new references from previously generated references.

Generate new current appearance from:

```text
canonical identity
+ body state
+ equipment state
```

This reduces visual drift.

---

# Face and Expression Library

Faces should be considered a separate visual subsystem.

Each character can gradually gain expressions such as:

```text
neutral
focused
angry
pain
fear
shock
exhausted
smirk
sad
rage
```

This is extremely useful because a close-up can function as a full manga panel without requiring body rendering.

The Visual Director can request:

```text
subject: Olof
framing: extreme_face_closeup
expression: focused
```

A close-up can make the same underlying action feel entirely different.

---

# Generic Fallback Library

A major requirement is that the game must work immediately even when a new character has almost no custom visual assets.

Therefore the project should include a strong universal fallback library.

These assets should intentionally reveal as little character-specific information as possible.

Examples:

- hand drawing a sword
- boots running
- hand opening a door
- silhouette swinging a weapon
- torso crop with face hidden
- cloak moving
- weapon closeup
- eyes in shadow
- bow being drawn
- arrow in flight
- object closeup
- impact frame
- blood/sparks/dust
- environment reaction

These can be designed to feel intentional rather than cheap.

The manga format makes this especially effective.

---

# Progressive Character-Specific Libraries

New players should not have to wait for a complete unique visual library before they can play.

The game should start with generic visuals and gradually improve character-specific coverage.

Possible visual maturity tiers:

```text
TIER 0
Generic visuals only

TIER 1
Portrait + basic closeups

TIER 2
Common character actions

TIER 3
Broader combat poses + expressions

TIER 4
Extensive personalized visual library
```

The exact tier system can change, but the core idea is:

> **The visual experience becomes more personalized over time without blocking gameplay.**

---

# Organic Asset Growth

The system can identify missing or valuable character-specific assets over time.

Example:

```text
Character performs action
    ↓
No strong specific asset exists
    ↓
Generic fallback is used immediately
    ↓
Missing visual coverage is recorded
    ↓
A character-specific asset can be generated later
    ↓
Asset enters staging
    ↓
Validation
    ↓
Published into character library
```

The character library therefore grows based on actual gameplay.

A sword fighter naturally accumulates sword-related visual assets.

An archer accumulates bow poses.

A mage accumulates casting/reaction assets.

The game does not need to generate an enormous identical asset package for every character at creation time.

---

# Asset Quality States

Generated assets should not automatically become trusted runtime content.

Use a lifecycle such as:

```text
GENERATED
    ↓
STAGING
    ↓
VALIDATED
    ↓
PUBLISHED
```

Possible libraries:

## Generic Runtime Library

Pre-approved universal visuals.

## Character Runtime Library

Approved character-specific visuals.

## Staging Library

Newly generated or experimental assets.

## Canon / Master Assets

High-quality long-term references.

This avoids permanently contaminating character identity with a bad generation.

---

# Asset Resolution and Graceful Fallback

The visual system should never depend on one exact image existing.

The Asset Resolver should search progressively.

Example:

```text
1. exact character-specific asset
2. compatible character-specific variant
3. generic rig-compatible asset
4. anonymous crop / silhouette
5. FX or object-only panel
6. environment-only panel
7. text/sound/dice only
```

This means missing assets reduce specificity rather than breaking gameplay.

The system should always degrade gracefully.

---

# Visual Snapshot

After a game event is resolved, the visual system should be able to capture what the world looked like at that moment.

Example:

```text
attacker:
    character_id: olof
    appearance_version: 14
    weapon: great_axe_01

target:
    character_id: goblin_4
    stance: bad_stance

environment:
    room_id: crypt_12
    visual_version: 6
```

This matters because characters and environments change later.

Old comic strips should still correspond to the state that existed when the event occurred.

This does not require converting the entire RPG into event sourcing.

It only means resolved events and the visual state used for them should be versionable/reproducible where useful.

---

# Visual Director

The Visual Director is one of the most important components.

Its responsibility is to decide how a resolved game event should be visually communicated.

It should work in semantic terms.

Example input:

```text
event: attack
result: hit
weapon_family: heavy_two_handed
damage_severity: high
stance_change: steady → bad_stance
```

Possible output:

```text
StripPlan

Panel 1
purpose: anticipation
subject: attacker
framing: face_close
expression: focused

Panel 2
purpose: action
subject: attacker
pose_family: overhead_attack
framing: torso
fx: heavy_speedlines

Panel 3
purpose: reaction
subject: defender
pose_family: stagger
framing: full
fx: heavy_impact
```

The Visual Director should not know specific image filenames.

It should request visual intent.

---

# Strip Plan

A strip plan describes the desired presentation before actual assets are selected.

Possible panel properties:

- purpose
- subject(s)
- pose family
- framing
- expression
- direction
- environment visibility
- impact level
- FX
- text/SFX
- camera style
- crop
- layout priority

The data model should allow a list of panels:

```text
ComicStrip
    panels: [...]
```

Do not hardcode exactly three panels.

V1 may normally use 1–3 panels, but the architecture should remain flexible.

---

# Asset Resolver

The Asset Resolver converts visual intent into concrete assets.

Example request:

```text
pose_family: overhead_attack
rig: humanoid_medium
weapon_grip: two_handed
framing: torso
direction: right
```

It might resolve to:

```text
pose: overhead_attack_03
character appearance: olof_v14
weapon: great_axe_01
armor layers: ...
crop: torso_close_02
```

This separation allows new assets to be added without changing combat logic or Visual Director rules.

---

# Asset Registry

Assets should be discovered through metadata rather than hardcoded paths.

Example pose metadata:

```json
{
  "id": "overhead_attack_03",
  "family": "overhead_attack",
  "rig_profile": "humanoid_medium_v1",
  "view": "three_quarter_front",
  "compatible_grips": [
    "two_handed"
  ],
  "mirror_safe": true,
  "recommended_crops": [
    "full",
    "torso"
  ]
}
```

The runtime should ask the registry for compatible assets.

It should not search arbitrary folders and infer meaning from filenames.

---

# Environment System

The environment should also have two representations:

```text
LOGICAL WORLD
exact game truth

VISUAL WORLD
how that place looks
```

Logical world state can include:

- room geometry
- doors
- walls
- objects
- elevation
- character/enemy positions
- collision
- destruction state

Visual environment state can include:

- room background
- lighting
- foreground
- midground
- horizon
- camera-compatible views
- destroyed wall variant
- open/closed door state
- fire/smoke
- weather

The logical representation remains authoritative.

Visual assets are derived from it.

---

# Dungeon / Room Workflow

A useful workflow is:

```text
1. Build logical dungeon/map
2. Add visual environment identity
3. Create active world state
4. Place enemies/characters logically
5. Use environment assets as comic backgrounds
```

Environment visuals can update when world state changes.

Example:

```text
wall_17:
intact → destroyed
```

Game state changes first.

The relevant environment visual can then be updated or regenerated.

---

# Background / Environment Slots

Combat and interaction templates should separate the action from the location.

Example:

```text
TEMPLATE
    background_slot
    character_slot
    weapon_slot
    fx_slot
```

The same attack pose can therefore be used in:

- a crypt
- a forest
- a throne room
- a ruined village
- a cave

This creates very high reuse.

---

# Perspective and Anchors

Reusable templates should eventually include spatial metadata.

Examples:

- ground line
- horizon
- actor anchor
- weapon anchor
- scale
- facing
- z-order
- foreground/midground/background relationship

This prevents characters from looking like stickers placed randomly over backgrounds.

---

# Mirroring

Horizontal mirroring can increase reuse, but not every asset is mirror-safe.

Potential problems:

- scars
- asymmetric armor
- handedness
- text
- symbols
- directional lighting
- unique equipment

Assets should therefore include:

```text
mirror_safe: true / false
```

Never assume every asset can be mirrored safely.

---

# Caching

The system should aggressively cache reusable visual results.

Possible cache inputs:

```text
character appearance version
pose version
equipment versions
weapon version
view
crop
```

Possible reuse levels:

- pose layer
- character pose composite
- equipment composite
- face expression
- final panel
- final strip

If a character has already been rendered in a pose with the same appearance/equipment, that result should often be reusable.

This reduces runtime generation and latency.

---

# Role of AI

AI should have clearly limited responsibilities.

## Good AI Responsibilities

### Intent Interpretation

Convert free-form player text into structured intent.

### Asset Authoring

Generate or refine:

- characters
- faces
- equipment
- environments
- enemies
- poses
- visual variants
- special FX

### Optional Rare-Scene Fallback

Later, truly unusual actions may use generative rendering.

Example:

> jump from balcony, grab chandelier, kick necromancer into altar

This should be a fallback for uncommon scenes, not the normal runtime path.

---

# What AI Should Not Control

AI should not directly determine:

- attack success
- damage
- saves
- HP
- inventory truth
- equipment ownership
- stance
- position
- death
- persistent world state

Those remain deterministic game-engine responsibilities.

---

# Runtime Philosophy

The ideal runtime becomes:

```text
GAME EVENT
    ↓
Visual Director
    ↓
Reusable assets
    ↓
Composition
    ↓
Comic strip
```

Not:

```text
GAME EVENT
    ↓
Generate entire image from scratch every time
```

The long-term goal is that common gameplay can use almost no runtime image generation.

AI creates and expands the library.

The game reuses it.

---

# Combat Template Library

The combat visual library can contain semantic pose/action families such as:

```text
attack_overhead
attack_horizontal
attack_thrust
attack_light
attack_heavy

block_high
block_low
parry

dodge_left
dodge_right
dodge_back

hit_light
hit_heavy
stagger
fall
prone
death

cast
bow_draw
bow_release

shield_bash
kick
```

Combat results select combinations of these based on actual mechanics.

---

# Interaction Template Library

Outside-combat visuals should have their own reusable families.

Examples:

```text
draw_weapon
sheath_weapon
open
close
inspect
reach
pick_up
hand_over
point
push
pull
kneel
sit
drink
light_torch
listen
threaten
greet
bow
whisper
look_back
react_surprised
react_angry
react_afraid
```

This library can become one of the most frequently used parts of the system.

---

# Comic Presentation Library

Pose and presentation should remain separate.

Presentation assets/rules can include:

```text
face_closeup
eye_closeup
torso_crop
full_body
object_closeup

horizontal_speedlines
radial_speedlines
heavy_impact
small_impact

normal_panel
vertical_panel
wide_panel
dramatic_panel
```

The same pose can therefore feel different through framing and composition.

---

# Visual Director as a Manga Director

The long-term Visual Director should effectively act as a deterministic manga director.

It chooses:

- what moment deserves a panel
- how many panels
- whose reaction matters
- when to show a face
- when to hide identity
- when to show the environment
- when to use an object closeup
- which pose family fits
- which FX fit
- how dramatic the layout should be

This is one of the main systems that can make the game feel authored rather than randomly illustrated.

---

# Dice and Sound

Dice should remain an important part of the presentation.

Existing/desired features include:

- animated d20s
- customizable die color
- customizable edge color
- customizable number color
- rolling sound
- settle sound
- special nat 1 feedback
- special nat 20 feedback

Dice, manga visuals, narration, and sound should reinforce each other.

Example:

```text
Player attacks
    ↓
D20 animation
    ↓
18 — HIT
    ↓
comic strip
    ↓
impact sound
    ↓
mechanical result / narration
```

---

# Motion Comic / Anime Layer

Full animation is not required for the initial system.

However, the architecture should not prevent it later.

Possible future visual types:

```text
static_panel
motion_panel
animated_panel
cinematic_sequence
```

A strong intermediate step is motion comic presentation:

- pan
- zoom
- parallax
- camera shake
- moving speedlines
- slash trails
- blinking light
- animated impact FX
- subtle hair/cape movement
- short loops

This can create an anime-like feeling without requiring full traditional animation.

Future progression could look like:

```text
V1
static manga panels

V2
motion comic

V3
short reusable animations

V4
special cinematic sequences
```

Animation should remain an enhancement of the comic system rather than a prerequisite.

---

# Key Data Concepts

The visual pipeline should preserve distinctions between these concepts.

## GameEvent

> What happened?

Example:

```text
Olof hit Goblin for 12 damage.
Goblin changed from steady to bad_stance.
```

## VisualSnapshot

> What did the world and participants look like at that moment?

## StripPlan

> How should the event be visually told?

## ResolvedStrip

> Which exact assets have been selected?

## Renderer Output

> The final PNG/WebP/animation shown in Discord.

Keeping these responsibilities separate will help prevent architectural coupling later.

---

# Suggested Module Boundaries

Conceptually:

```text
game/
    combat/
    characters/
    inventory/
    world/

interpretation/
    intents/
    parser/
    validation/

visuals/
    events/
    snapshots/
    director/
    policies/
    strips/
    assets/
    registry/
    resolver/
    rigs/
    characters/
    equipment/
    environments/
    compositor/
    cache/
    validation/

discord/
    commands/
    interactions/
    presentation/
```

Exact folders can change.

The important part is dependency direction and responsibility.

---

# Important Architectural Rule

Avoid dependencies like:

```text
CombatService
    ↓
ComicRenderer
    ↓
Discord
    ↓
CharacterRepository
    ↓
AI
    ↓
CombatService
```

Prefer:

```text
Discord
    ↓
Application/Game Engine
    ↓
Resolved Game Event

Resolved Game Event
    ↓
Visual Pipeline
    ↓
Rendered Result

Rendered Result
    ↓
Discord
```

The visual layer should consume game results.

The game layer should not depend on visual implementation details.

---

# User Experience Goal

A successful session should feel approximately like this:

```text
Player:
"I slowly open the door."

↓ interpretation

↓ game state update

[small manga panel]
hand on old wooden door
CREEEAK...

Narration:
Cold air spills from the chamber beyond.
```

Later:

```text
Player:
"I draw my sword."

[close-up panel]
SHHKK
```

Then combat:

```text
[D20 spins]

18
HIT

[attacker manga panel]
WHOOSH

[target reaction panel]
KRAK

Target: bad_stance
```

Then roleplay continues:

```text
Player:
"I wipe the blade clean and look at the prisoner."

[small character panel]

NPC:
"..."
```

The visual language should remain consistent across exploration, roleplay, and combat.

The player is not switching between “text mode” and “combat graphics mode”.

They are continuously playing inside the same comic world.

---

# Content Strategy

Do not try to build thousands of assets before the game is playable.

Start narrow.

Possible early scope:

- one reusable humanoid rig
- a small number of weapon families
- roughly 20–30 highly reusable poses
- basic face/expression support
- a generic anonymous fallback library
- a few environment types
- a small combat template set
- a small interaction template set
- 1–3 panel strips
- one character per panel
- deterministic selection
- no required runtime image generation for common actions

Then expand based on actual gameplay needs.

---

# Main Risk

The biggest risk is not the concept.

It is content volume and visual consistency.

The architecture should therefore optimize for:

- reuse
- modularity
- caching
- progressive coverage
- graceful fallbacks
- versioned assets
- separation of truth and presentation

The generic fallback library is especially important because it allows gameplay to start immediately while personalized libraries grow naturally.

---

# End Goal

The finished system should feel like:

> **A multiplayer RPG played through Discord where players can freely describe what they do, the game interprets and resolves those actions using real deterministic game state, and meaningful moments are automatically directed into manga/comic panels, strips, dice animations, sound, and eventually motion-comic/anime-like presentation.**

The world remains persistent.

Characters remain visually recognizable.

Their equipment and injuries matter.

The environment reflects the current game state.

Combat mechanics determine what actually happens.

The visual system transforms those events into dramatic visual storytelling.

The ultimate experience is not simply reading an RPG log.

It is:

> **playing a story and watching your group's manga appear while you create it.**
