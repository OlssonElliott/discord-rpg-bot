# Lightweight Discord RPG Bot

A small mechanical assistant for a human-run tabletop RPG campaign. It stores one
character per Discord user, rolls dice, displays character status, and gives the
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
   permission needed for this milestone is **Send Messages**; **Embed Links**
   should also be allowed so responses render as intended. The older portal UI
   exposes the equivalent settings under **OAuth2 > URL Generator**.
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
DISCORD_GUILD_ID=your_numeric_server_id
```

Create a role named exactly `DM` in **Server Settings > Roles**, then assign it to
each Dungeon Master. To use another name, change `DM_ROLE_NAME` in `.env`. Role
matching is case-sensitive.

## Run the bot

With the virtual environment active:

```powershell
python bot.py
```

The console logs successful login and command synchronization. With
`DISCORD_GUILD_ID` configured, commands are copied and synchronized to that server
at startup. Without it, commands are registered globally; Discord may take up to
about an hour to show global command changes.

Stop the process with Ctrl+C. Character data is stored in `rpg_bot.db` by default
and survives restarts. The database and `.env` are ignored by Git.

## Commands

Player commands:

- `/roll expression` — accepts forms such as `d20`, `1d20+4`, and `2d6-3`.
- `/status` — shows the calling user's character, HP, and stance.

DM-role commands:

- `/createcharacter user name max_hp`
- `/damage user amount`
- `/heal user amount`
- `/stance user stance`
- `/sethp user hp`

Each Discord user ID can have one character. Damage stops at 0 HP, healing stops
at maximum HP, and manual HP must be between those bounds. The allowed stances are
`steady`, `bad_stance`, and `prone`.

## Verify locally

The unit tests exercise dice parsing, HP rules, stance changes, and persistence
without connecting to Discord:

```powershell
python -m unittest discover -s tests -v
```

## Project structure

```text
bot.py                startup, synchronization, and top-level error logging
config.py             .env configuration
database.py           SQLite character persistence
models.py             character and stance domain types
dice.py               bounded dice parser and roller
checks.py             reusable DM-role permission check
commands/player.py    /roll and /status
commands/dm.py        DM character-management commands
tests/                mechanics and persistence tests
```
