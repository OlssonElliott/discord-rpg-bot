# Lightweight Discord RPG Bot

A small mechanical assistant for a human-run tabletop RPG campaign. It stores multiple
characters per Discord user, rolls dice, displays character status, and gives the
DM a few character-management commands. Storytelling and rulings remain with the
human DM.

## Requirements and installation

- Python 3.12 or newer
- A Discord account and a server where you can manage applications/roles

From PowerShell in this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

On macOS or Linux, activate the environment with `source .venv/bin/activate` and
copy the environment file with `cp .env.example .env`.

## Create and configure the Discord bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications)
   and select **New Application**.
2. Open **Bot**, select **Add Bot** if needed, then use **Reset Token**. Copy the
   token into `.env` as `DISCORD_TOKEN`. Never post or commit this token.
3. No privileged gateway intents are required. The bot uses Discord's default
   intents and slash-command interactions.
4. Open **Installation**, make sure **Guild Install** is enabled under Installation
   Contexts, and choose **Discord Provided Link**. Under the Guild Install default
   settings, include the `bot` and `applications.commands` scopes. The only bot
   permissions needed are **Send Messages**, **Embed Links**, **Connect**, and
   **Speak**. The voice permissions allow the optional dice sounds. The older
   portal UI exposes the equivalent settings under **OAuth2 > URL Generator**.
5. Use the generated install link, choose your server, and authorize the bot.
6. In Discord, enable **Developer Mode** under **User Settings > Advanced**,
   right-click the server, and select **Copy Server ID**. Put it in `.env` as
   `DISCORD_GUILD_ID`. This is recommended during development because guild
   commands update almost immediately.

Your `.env` should resemble:

```dotenv
DISCORD_TOKEN=your_real_token_here
DM_ROLE_NAME=DM
DATABASE_PATH=rpg_bot.db
CHARACTER_MEDIA_PATH=data/characters
DICE_THEME=classic
DISCORD_GUILD_ID=your_numeric_server_id
```

Create a role named exactly `DM` in **Server Settings > Roles**, then assign it to
each Dungeon Master. To use another name, change `DM_ROLE_NAME` in `.env`. Role
matching is case-sensitive.

## Run the game

After installing both Python and dashboard dependencies, start the complete local
development setup from the repository root:

```powershell
npm --prefix dashboard install
npm run dev
```

This one command starts the Discord bot, dashboard API, and web dashboard in the
same terminal, then opens `http://localhost:3000`. Stop all processes with Ctrl+C.
The console logs successful login and command synchronization. With
`DISCORD_GUILD_ID` configured, commands are copied and synchronized to that server
at startup. Without it, commands are registered globally; Discord may take up to
about an hour to show global command changes.

Character data is stored in `rpg_bot.db` by default and survives restarts. The
database and `.env` are ignored by Git.

## Run the DM location editor

The local dashboard uses the same SQLite database and deterministic world service
as Discord and is included in `npm run dev`. Create or select an Area, add locations,
drag them into place, and connect them by dragging from one node handle to another.
Create reusable item types once in **Item library**; rooms can only receive items
selected from that shared catalog, so anything taken with `/take` appears in the
same interactive `/inventory`. Node positions are editor-only metadata; arrows are
persisted directional gameplay exits. The API binds to localhost and is intended
for the DM's local machine.

## Commands

Player commands:

- `/character create` — start a private, step-by-step character creation session.
- `/character manage` — choose an active character or archive one from Discord.
- `/character sheet` — privately open the active character's full sheet, including
  attribute scores and roll modifiers; use **Publish here** to create or update the
  character's persistent sheet in whichever channel the command was used.
- `/character portrait [image] [remove]` — view the active portrait, attach a file
  to replace it, or use `remove: True` to remove it directly. A DM with no active
  character manages their personal Dungeon Master portrait instead.
- `/character removeportrait` — remove the active character's portrait.
- `/character cancel` — discard the active creation session.
- `/inventory` — privately open the active character's equipment, flat inventory,
  item details, and inventory actions. An open view refreshes after taking or
  dropping an item.
- `/roll expression [mode]` — accepts forms such as `d20`, `1d20+4`, and
  `2d6-3`; mode can be Normal, Advantage, or Disadvantage.
- `/dicecolor [color]` — view or set a personal six-digit hex dice color.
- `/diceedgecolor [color]` — view or set a personal dice edge color.
- `/dicenumbercolor [color]` — view or set a personal dice number color.
- `/status` — shows the calling user's character, HP, and stance.

DM-role commands:

- `/damage user amount`
- `/heal user amount`
- `/stance user stance`
- `/sethp user hp`
- `/giveitem user item [quantity]` — give an item or consumable stack to the
  user's active character.

Each Discord user ID can have multiple characters and one active character at a time.
Damage stops at 0 HP, healing stops at maximum HP, and manual HP must be between
those bounds. The allowed stances are
`steady`, `bad_stance`, and `prone`.

Character creation uses private dropdowns, a name modal, number-to-attribute linking
for the standard array, and `+`/`−` buttons for bonus points. Every step has back
navigation, and the bonus step previews scores with race and age modifiers. It validates
lineage, race, age, gender, attributes, and two starting skill trees.
Finished characters are stored against the calling Discord user, who may own more
than one while using one active character at a time. A newly created character becomes
active automatically. `/character manage` can also unequip the active character, which
is useful for generic DM rolls. Archiving removes a character from Discord selection
without deleting its database record. Final Vitality becomes starting and maximum HP. Active,
incomplete creation sessions are held in memory and need to be restarted after a bot
restart.

Inventory ownership and equipment are stored in SQLite, while reusable item
templates are managed through the dashboard's **Item library** and persisted in
`assets/items/items.json`. Item weight and inventory storage are separate
measurements: equipped items still count toward carried weight but do not occupy
storage. A loose backpack is an ordinary inventory item; equipping it adds its
capacity to the character's storage limit. Inventory is intentionally flat, and
older nested contents are moved to that flat inventory automatically at startup.
Every character starts with weightless **Common Clothing** in a separate clothing
slot beneath armor. Removing armor leaves the clothing equipped; removing the
clothing itself shows the character as **Nude** until clothing is equipped again.
Consumables of the same type stack by quantity. The private character sheet links
directly to the same inventory UI.

Character portraits accept PNG, JPEG, and WebP files up to 5 MB. They are safely
cropped to a 256×256 WebP, stripped of uploaded metadata, and stored below
`CHARACTER_MEDIA_PATH` (default `data/characters`). Portraits appear on dice rolls
and `/status`. The upload confirmation and `/character manage` both provide a
button for removing a custom portrait; archiving keeps it with the archived record.
New characters use the bundled race portrait (and the male/female variant where
available) until the player uploads one. Removing a custom portrait restores that
default automatically.
DMs without an active character can upload a personal portrait through the same
command. It appears on their DM rolls, and removing it restores the bundled Dungeon
Master portrait.

Dice body, edge, and number colors are stored separately from characters, so a DM
without a character can use all three color commands. Discord suggests a small
palette while typing, but any valid six-digit RGB hex color is accepted. Values
such as `7a2eff` are normalized to `#7A2EFF`; the defaults are `#C89B3C` for the
body, `#303030` for the edges, and `#101010` for the numbers.

## Optional visual dice animations

Single d4, d6, d8, d10, d12, and d20 rolls can use themed master animations.
Each die type follows the same layout; for example:

```text
assets/dice/
    d4/themes/cartoon/d4_1.gif ... d4_4.gif
    d6/themes/cartoon/d6_1.gif ... d6_6.gif
    d8/themes/cartoon/d8_1.gif ... d8_8.gif
    d10/themes/cartoon/d10_1.gif ... d10_10.gif
    d12/themes/cartoon/d12_1.gif ... d12_12.gif
    d20/themes/cartoon/d20_1.gif ... d20_20.gif
```

Every master also has matching `_edges.gif` and `_numbers.gif` masks. Each
animation finishes on the natural result in its filename and has a transparent
background. The Python roller chooses the result first; the matching GIF is only
a visual presentation of that result. `DICE_THEME` selects one global theme. If
that theme or result is missing, Rollkeeper tries `classic`, then sends the normal
instant result if no animation is available. Restart the bot after changing
`DICE_THEME`.

For supported dice, the bot tints neutral pixels while preserving shadows,
restrained highlights, markings, transparency, and chromatic background elements.
Bright neutral faces retain the selected body color instead of fading to white. The matching
`_edges.gif` and `_numbers.gif` are synchronized masks that allow each player to
tint the beveled divisions and face numbers independently. Older themes without
these masks still work and retain their baked appearance. Generated GIFs are
separated by theme, body, edge, and number color, for example
`assets/dice/d20/cache/v2/cartoon/7A2EFF/FFD700/F5F5F5/d20_17.gif`. A newer master or
mask automatically invalidates its generated cache. The settled frame is also
cached as a transparent 160x160 PNG and displayed as the result embed's thumbnail.
Each complete body/edge/number color cache is retained while it is used. A cache
that has not been used for 90 days is removed by the bot's daily cleanup check;
existing untracked caches receive a fresh 90-day period after upgrading.
Rolls containing two to ten matching dice, such as `3d6`, reuse those tinted GIFs
in one synchronized side-by-side animation. The final embed displays every result
at the same size in one horizontal row and preserves the original roll order.
These group animations and result images are cached as well. Larger pools continue
to use the normal instant result so the Discord upload stays compact and the dice
remain readable.

For advantage or disadvantage, select the corresponding `mode` option on a single
d20 expression such as `/roll expression:1d20+4 mode:Advantage`. Rollkeeper rolls
two d20s, applies the modifier once, and keeps the higher or lower natural result.
Both dice animate together with a green advantage glow or red disadvantage glow.
The kept result is marked in the embed, while both result dice remain equally sized
in the final row. Other expressions use Normal mode.

### Dice sounds in voice

When the player who invokes `/roll` is in a voice channel, Rollkeeper joins that
channel for the first visual roll and stays connected until the bot shuts down or
is disconnected. Later roll sounds play only when the roller is in that same voice
channel. Players can mute Rollkeeper or set its volume individually in Discord.

The sound sequence consists of a 1.4-second spin followed by a separate landing
sound. A kept natural 1 or natural 20 on a d20 adds its own short sting. For
ordinary d20 pools, natural 20 takes precedence if both special results occur. If
the player is not in voice, the bot is already connected elsewhere, another roll
sound is playing, assets are missing, or voice permissions are unavailable, the
visual roll continues silently.

Rollkeeper only plays finished 48 kHz stereo PCM WAV assets committed under
`assets/audio/dice/`. It does not generate or synthesize sounds at runtime or via
a repository tool.

### Generate all master animations

The offline generator creates complete neutral master sets; Blender is only an
asset-development dependency and is never imported or launched by the Discord bot.
The default output is 384x384, 20 FPS, 29 rendered frames, and 2.3 seconds per GIF.
The complete die rotates horizontally from left to right around a stable axis,
without travelling, vertical bobbing, or bouncing. A continuous ease-out curve
keeps faces, edges, and numbers moving as one object. The rotation settles into
the exact result and the GIF holds it completely still for 0.9 seconds. GIFs are
saved for a single playback so Discord cannot begin a second roll cycle after the
readable result. The shared procedural models use broad bevels, matte grayscale faces, crisp
high-contrast numbers, subtle per-face luminance variation, and directional
grayscale lighting for a chunky illustrated look that remains suitable for
tinting. The face tones rotate with the geometry so the body and numbers read as
one moving object.

Requirements:

- The project's Python 3.12 environment with `requirements.txt` installed (Pillow
  performs GIF encoding).
- Blender 4.2 or newer. On Windows, download the current LTS installer from the
  [official Blender download page](https://www.blender.org/download/), install it,
  and either add Blender to `PATH` or pass the full path to `blender.exe`.

From PowerShell at the repository root, generate every supported die for the
cartoon theme with:

```powershell
python scripts\generate_d20_assets.py --theme cartoon --sides 4 6 8 10 12 20
```

Generate only a preview selection for one die type with:

```powershell
python scripts\generate_d20_assets.py --theme cartoon --sides 10 --results 1 5 10
```

Omitting `--sides` preserves the historical d20-only default. Omitting `--results`
renders every face for each selected die. Existing theme GIFs cause the command to
stop before Blender starts. Replace all supported cartoon files intentionally with:

```powershell
python scripts\generate_d20_assets.py --theme cartoon --sides 4 6 8 10 12 20 --overwrite
```

The generator searches `PATH` and normal `C:\Program Files\Blender Foundation\`
install locations. If automatic discovery does not find Blender, run:

```powershell
python scripts\generate_d20_assets.py --theme cartoon `
  --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
```

To retain intermediate PNGs while checking the scene, add `--keep-frames
build\d20-frames`. Otherwise they use a temporary folder and are removed
automatically. New GIFs are encoded atomically.

The old `assets/dice/d20/master/` directory remains supported for compatibility.
Whenever the generator runs, legacy `d20_*.gif` files are copied into missing
slots under `themes/classic/`; legacy files and existing classic files are never
deleted or overwritten by this migration.

Activate a generated theme in `.env`, then restart Rollkeeper:

```dotenv
DICE_THEME=cartoon
```

Theme names may contain lowercase letters, numbers, and single hyphens, such as
`classic`, `chunky`, or `dark-fantasy`. Paths and malformed names are rejected.

Each procedural solid has one modeled number per face, with opposing or most-opposed
faces paired to sum to `sides + 1`. The d10 uses the conventional tall pentagonal
trapezohedron shape. For result N, the generator maps that face's outward normal to
the camera and its local display axis to screen-up. Blender then rotates the complete
numbered geometry around the camera's vertical axis. Each run emits the neutral
master plus synchronized edge and number masks.

On a typical recent desktop, all 60 result animations should take roughly 8–25
minutes to render; integrated or older hardware may take longer. At the defaults,
expect approximately 0.2–1.2 MiB for each master-and-mask set depending on die type,
Blender version, and image complexity. The generator prints measured time, duration,
and file size when it finishes.
Blender supports background command-line rendering as documented in the
[official manual](https://docs.blender.org/manual/en/4.5/advanced/command_line/render.html).

## Verify locally

The unit tests exercise dice parsing, HP rules, stance changes, and persistence
without connecting to Discord:

```powershell
python -m unittest discover -s tests -v
```

## Project structure

```text
rpg_bot/__main__.py             startup, synchronization, and top-level error logging
rpg_bot/config.py               .env configuration
rpg_bot/database.py             SQLite character persistence
rpg_bot/models.py               character and stance domain types
rpg_bot/dice.py                 bounded dice parser and roller
rpg_bot/dice_audio.py           voice connection and sequential dice sound playback
rpg_bot/dice_assets.py          safe themed asset and cache path resolution
rpg_bot/dice_visuals.py         dice color validation, GIF tinting, and generated cache
rpg_bot/inventory.py            item catalog, instances, equipment, and measurements
rpg_bot/inventory_service.py    validated inventory and equipment operations
rpg_bot/checks.py               reusable DM-role permission check
rpg_bot/commands/player.py      /roll and /status
rpg_bot/commands/dm.py          DM character and item-management commands
rpg_bot/commands/character.py   /character creation command group and user sessions
rpg_bot/commands/inventory.py   private interactive inventory browser
rpg_bot/character_creation/     UI-independent rules, state machine, and persistence service
rpg_bot/world.py                area, room, entity, inventory, and graph domain types
rpg_bot/world_service.py        deterministic world and editor application service
assets/items/items.json         reusable item template catalog
rpg_bot/dashboard_api.py        framework-neutral DM dashboard JSON API
rpg_bot/dashboard_server.py     localhost API server for the React dashboard
dashboard/                      React Flow visual location editor
docs/END_GOAL.md                long-term product vision
scripts/generate_d20_assets.py  offline multi-die Blender orchestration and GIF encoding
scripts/render_d20_blender.py   procedural dice scenes and deterministic PNG rendering
tests/                mechanics and persistence tests
```
