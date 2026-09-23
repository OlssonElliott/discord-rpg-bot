"""World schema creation, migration, and seed helpers."""

from __future__ import annotations

import sqlite3
from uuid import uuid4


class DatabaseWorldSchemaMixin:
    """Create and migrate world-related database tables."""

    @staticmethod
    def _initialize_world(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS areas (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT
            );
            CREATE TABLE IF NOT EXISTS rooms (
                id TEXT PRIMARY KEY,
                area_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                floor_id TEXT,
                width REAL NOT NULL DEFAULT 1,
                height REAL NOT NULL DEFAULT 1,
                scene_image_path TEXT,
                scene_image_url TEXT,
                scene_prompt TEXT,
                FOREIGN KEY (area_id) REFERENCES areas(id)
            );
            CREATE TABLE IF NOT EXISTS room_exits (
                room_id TEXT NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                destination_room_id TEXT NOT NULL,
                PRIMARY KEY (room_id, name),
                FOREIGN KEY (room_id) REFERENCES rooms(id),
                FOREIGN KEY (destination_room_id) REFERENCES rooms(id)
            );
            CREATE TABLE IF NOT EXISTS room_editor_metadata (
                room_id TEXT PRIMARY KEY,
                x REAL NOT NULL,
                y REAL NOT NULL,
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS world_entities (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('enemy', 'npc', 'container')),
                name TEXT NOT NULL,
                description TEXT,
                FOREIGN KEY (room_id) REFERENCES rooms(id)
            );
            CREATE TABLE IF NOT EXISTS enemy_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                race TEXT NOT NULL DEFAULT 'Unknown',
                difficulty_level INTEGER NOT NULL DEFAULT 1 CHECK (difficulty_level >= 0),
                strength INTEGER NOT NULL DEFAULT 0 CHECK (strength >= 0),
                dexterity INTEGER NOT NULL DEFAULT 0 CHECK (dexterity >= 0),
                arcana INTEGER NOT NULL DEFAULT 0 CHECK (arcana >= 0),
                vitality INTEGER NOT NULL DEFAULT 0 CHECK (vitality >= 0),
                insight INTEGER NOT NULL DEFAULT 0 CHECK (insight >= 0),
                personality INTEGER NOT NULL DEFAULT 0 CHECK (personality >= 0),
                max_hp INTEGER NOT NULL DEFAULT 7 CHECK (max_hp > 0),
                armor INTEGER NOT NULL DEFAULT 0 CHECK (armor >= 0),
                magical_resistance INTEGER NOT NULL DEFAULT 0 CHECK (magical_resistance >= 0),
                attack_dc INTEGER NOT NULL DEFAULT 12 CHECK (attack_dc > 0),
                defense_dc INTEGER NOT NULL DEFAULT 12 CHECK (defense_dc > 0),
                damage TEXT NOT NULL DEFAULT '1d4',
                attack_profile TEXT NOT NULL DEFAULT 'Basic attack',
                special_ability TEXT,
                typical_behaviour TEXT NOT NULL DEFAULT 'Unknown',
                main_hand_item_id TEXT,
                off_hand_item_id TEXT,
                armor_item_id TEXT
            );
            CREATE TABLE IF NOT EXISTS world_enemies (
                entity_id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                current_hp INTEGER NOT NULL CHECK (current_hp >= 0),
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'dead', 'fled')),
                FOREIGN KEY (entity_id) REFERENCES world_entities(id) ON DELETE CASCADE,
                FOREIGN KEY (template_id) REFERENCES enemy_templates(id)
            );
            CREATE INDEX IF NOT EXISTS world_enemies_by_template
                ON world_enemies(template_id);
            CREATE TABLE IF NOT EXISTS world_seed_state (
                key TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS container_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                container_type TEXT NOT NULL,
                description TEXT,
                default_has_lock INTEGER NOT NULL DEFAULT 0 CHECK (
                    default_has_lock IN (0, 1)
                ),
                default_is_locked INTEGER NOT NULL DEFAULT 0 CHECK (
                    default_is_locked IN (0, 1)
                ),
                default_is_broken INTEGER NOT NULL DEFAULT 0 CHECK (
                    default_is_broken IN (0, 1)
                ),
                default_unlock_difficulty INTEGER CHECK (
                    default_unlock_difficulty BETWEEN 1 AND 30
                ),
                default_hidden INTEGER NOT NULL DEFAULT 0 CHECK (
                    default_hidden IN (0, 1)
                ),
                default_discovery_difficulty INTEGER CHECK (
                    default_discovery_difficulty BETWEEN 1 AND 30
                )
            );
            CREATE TABLE IF NOT EXISTS world_containers (
                entity_id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                has_lock INTEGER NOT NULL DEFAULT 0 CHECK (has_lock IN (0, 1)),
                is_locked INTEGER NOT NULL DEFAULT 0 CHECK (is_locked IN (0, 1)),
                is_broken INTEGER NOT NULL DEFAULT 0 CHECK (is_broken IN (0, 1)),
                unlock_difficulty INTEGER CHECK (
                    unlock_difficulty BETWEEN 1 AND 30
                ),
                hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
                discovery_difficulty INTEGER CHECK (
                    discovery_difficulty BETWEEN 1 AND 30
                ),
                is_open INTEGER NOT NULL DEFAULT 0 CHECK (is_open IN (0, 1)),
                searched INTEGER NOT NULL DEFAULT 0 CHECK (searched IN (0, 1)),
                FOREIGN KEY (entity_id) REFERENCES world_entities(id) ON DELETE CASCADE,
                FOREIGN KEY (template_id) REFERENCES container_templates(id)
            );
            CREATE TABLE IF NOT EXISTS character_known_containers (
                character_id INTEGER NOT NULL,
                container_id TEXT NOT NULL,
                PRIMARY KEY (character_id, container_id),
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
                FOREIGN KEY (container_id) REFERENCES world_entities(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS containers_by_template
                ON world_containers(template_id);
            INSERT OR IGNORE INTO container_templates (
                id, name, container_type, default_has_lock, default_is_locked,
                default_is_broken, default_unlock_difficulty, default_hidden,
                default_discovery_difficulty
            ) VALUES
                ('wooden_chest', 'Wooden Chest', 'wooden_chest', 0, 0, 0, NULL, 0, NULL),
                ('reinforced_chest', 'Reinforced Chest', 'reinforced_chest', 1, 1, 0, 14, 0, NULL),
                ('barrel', 'Barrel', 'barrel', 0, 0, 0, NULL, 0, NULL),
                ('crate', 'Crate', 'crate', 0, 0, 0, NULL, 0, NULL),
                ('shelf', 'Shelf', 'shelf', 0, 0, 0, NULL, 0, NULL),
                ('bookshelf', 'Bookshelf', 'bookshelf', 0, 0, 0, NULL, 0, NULL),
                ('corpse', 'Corpse', 'corpse', 0, 0, 0, NULL, 0, NULL),
                ('skeleton', 'Skeleton', 'skeleton', 0, 0, 0, NULL, 0, NULL),
                ('backpack', 'Backpack', 'backpack', 0, 0, 0, NULL, 0, NULL),
                ('hidden_compartment', 'Hidden Compartment', 'hidden_compartment', 0, 0, 0, NULL, 1, 14),
                ('loose_floorboard', 'Loose Floorboard', 'loose_floorboard', 0, 0, 0, NULL, 1, 14),
                ('other', 'Other', 'other', 0, 0, 0, NULL, 0, NULL);
            INSERT OR IGNORE INTO world_containers (
                entity_id, template_id, has_lock, is_locked, is_broken,
                unlock_difficulty, hidden, discovery_difficulty, is_open, searched
            )
            SELECT id, 'other', 0, 0, 0, NULL, 0, NULL, 0, 0
            FROM world_entities
            WHERE kind = 'container';
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                stackable INTEGER NOT NULL DEFAULT 1 CHECK (stackable IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS inventory_stacks (
                holder_kind TEXT NOT NULL CHECK (
                    holder_kind IN ('character', 'room', 'entity')
                ),
                holder_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                PRIMARY KEY (holder_kind, holder_id, item_id),
                FOREIGN KEY (item_id) REFERENCES items(id)
            );
            CREATE INDEX IF NOT EXISTS entities_by_room ON world_entities(room_id);
            CREATE INDEX IF NOT EXISTS characters_by_room ON characters(current_room_id);
            """
        )
        enemy_seed_key = "basic_enemy_templates_v1"
        if connection.execute(
            "SELECT 1 FROM world_seed_state WHERE key = ?",
            (enemy_seed_key,),
        ).fetchone() is None:
            connection.executemany(
                """
                INSERT OR IGNORE INTO enemy_templates (
                    id, name, description, race, difficulty_level,
                    strength, dexterity, arcana, vitality, insight, personality,
                    max_hp, armor, magical_resistance, attack_dc, defense_dc,
                    damage, attack_profile, special_ability, typical_behaviour
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    (
                        "core_goblin_raider",
                        "Goblin Raider",
                        "A wiry goblin skirmisher accustomed to ambushes and dirty fighting.",
                        "Goblin",
                        1, 1, 3, 0, 1, 1, 0, 6, 0, 0, 12, 13,
                        "1d4",
                        "Jagged blade or shortbow",
                        "Pack opportunist",
                        "Circles isolated targets, attacks from advantage, and retreats when pressured.",
                    ),
                    (
                        "core_bandit",
                        "Bandit",
                        "A common outlaw with practical weapons and little discipline.",
                        "Human",
                        1, 2, 2, 0, 2, 1, 1, 9, 1, 0, 12, 12,
                        "1d6",
                        "Sword or club",
                        None,
                        "Fights directly while an advantage remains and may flee when badly hurt.",
                    ),
                    (
                        "core_skeleton_warrior",
                        "Skeleton Warrior",
                        "An animated warrior held together by old armor and darker forces.",
                        "Undead",
                        2, 3, 1, 0, 3, 0, 0, 10, 1, 1, 13, 11,
                        "1d6",
                        "Heavy weapon swing",
                        "Fearless",
                        "Advances without hesitation and keeps pressure on the nearest living target.",
                    ),
                    (
                        "core_bone_hound",
                        "Bone Hound",
                        "A fast skeletal predator that hunts by sound and movement.",
                        "Undead Beast",
                        2, 2, 4, 0, 2, 2, 0, 8, 0, 1, 13, 13,
                        "1d6",
                        "Bite and maul",
                        "Relentless pursuit",
                        "Rushes vulnerable targets and stays close once it has engaged.",
                    ),
                    (
                        "core_cultist",
                        "Cultist",
                        "A fanatical occultist carrying crude weapons and unstable magic.",
                        "Human",
                        2, 1, 2, 4, 1, 2, 2, 7, 0, 2, 13, 11,
                        "1d4",
                        "Ritual blade or dark bolt",
                        "Dark invocation",
                        "Keeps distance when possible and supports stronger allies with occult pressure.",
                    ),
                    (
                        "core_swamp_troll",
                        "Swamp Troll",
                        "A massive troll accustomed to fighting through wounds that would stop lesser creatures.",
                        "Troll",
                        4, 6, 1, 0, 6, 1, 0, 28, 2, 1, 15, 10,
                        "2d6",
                        "Crushing claw or heavy club",
                        "Regeneration",
                        "Pushes into the center of a fight and focuses on the nearest threatening target.",
                    ),
                ),
            )
            connection.execute(
                "INSERT INTO world_seed_state (key) VALUES (?)",
                (enemy_seed_key,),
            )
        room_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(rooms)")
        }
        room_migrations = {
            "floor_id": "ALTER TABLE rooms ADD COLUMN floor_id TEXT",
            "width": "ALTER TABLE rooms ADD COLUMN width REAL NOT NULL DEFAULT 1",
            "height": "ALTER TABLE rooms ADD COLUMN height REAL NOT NULL DEFAULT 1",
            "scene_image_path": "ALTER TABLE rooms ADD COLUMN scene_image_path TEXT",
            "scene_image_url": "ALTER TABLE rooms ADD COLUMN scene_image_url TEXT",
            "scene_prompt": "ALTER TABLE rooms ADD COLUMN scene_prompt TEXT",
        }
        for column, statement in room_migrations.items():
            if column not in room_columns:
                connection.execute(statement)
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS dungeon_floors (
                id TEXT PRIMARY KEY,
                dungeon_id TEXT NOT NULL,
                floor_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                UNIQUE (dungeon_id, floor_number),
                FOREIGN KEY (dungeon_id) REFERENCES areas(id)
            );
            CREATE TABLE IF NOT EXISTS room_connections (
                id TEXT PRIMARY KEY,
                from_room_id TEXT NOT NULL,
                to_room_id TEXT NOT NULL,
                exit_name TEXT NOT NULL,
                return_exit_name TEXT,
                connection_type TEXT NOT NULL,
                hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
                bidirectional INTEGER NOT NULL DEFAULT 0 CHECK (bidirectional IN (0, 1)),
                has_lock INTEGER NOT NULL DEFAULT 0 CHECK (has_lock IN (0, 1)),
                is_locked INTEGER NOT NULL DEFAULT 0 CHECK (is_locked IN (0, 1)),
                is_broken INTEGER NOT NULL DEFAULT 0 CHECK (is_broken IN (0, 1)),
                is_open INTEGER NOT NULL DEFAULT 0 CHECK (is_open IN (0, 1)),
                unlock_difficulty INTEGER CHECK (
                    unlock_difficulty BETWEEN 1 AND 30
                ),
                has_trap INTEGER NOT NULL DEFAULT 0 CHECK (has_trap IN (0, 1)),
                trap_state TEXT CHECK (
                    trap_state IN ('armed', 'disarmed', 'triggered')
                ),
                trap_detection_difficulty INTEGER CHECK (
                    trap_detection_difficulty BETWEEN 1 AND 30
                ),
                trap_damage_type TEXT,
                trap_damage INTEGER CHECK (trap_damage > 0),
                FOREIGN KEY (from_room_id) REFERENCES rooms(id),
                FOREIGN KEY (to_room_id) REFERENCES rooms(id)
            );
            CREATE TABLE IF NOT EXISTS character_room_knowledge (
                character_id INTEGER NOT NULL,
                room_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('known', 'visited')),
                source TEXT NOT NULL CHECK (source IN ('discovered', 'shared')),
                first_visited_at TEXT,
                last_visited_at TEXT,
                last_seen_scene_id TEXT,
                shared_by_character_id INTEGER,
                PRIMARY KEY (character_id, room_id),
                FOREIGN KEY (character_id) REFERENCES characters(id),
                FOREIGN KEY (room_id) REFERENCES rooms(id),
                FOREIGN KEY (shared_by_character_id) REFERENCES characters(id)
            );
            CREATE TABLE IF NOT EXISTS character_known_connections (
                character_id INTEGER NOT NULL,
                connection_id TEXT NOT NULL,
                PRIMARY KEY (character_id, connection_id),
                FOREIGN KEY (character_id) REFERENCES characters(id),
                FOREIGN KEY (connection_id) REFERENCES room_connections(id)
            );
            CREATE TABLE IF NOT EXISTS player_view_states (
                character_id INTEGER PRIMARY KEY,
                selected_floor_id TEXT,
                focused_room_id TEXT,
                discord_channel_id INTEGER,
                discord_message_id INTEGER,
                FOREIGN KEY (character_id) REFERENCES characters(id),
                FOREIGN KEY (selected_floor_id) REFERENCES dungeon_floors(id),
                FOREIGN KEY (focused_room_id) REFERENCES rooms(id)
            );
            CREATE TABLE IF NOT EXISTS player_map_refresh_requests (
                character_id INTEGER PRIMARY KEY,
                requested_at TEXT NOT NULL,
                FOREIGN KEY (character_id) REFERENCES characters(id)
            );
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                lock_state TEXT NOT NULL CHECK (
                    lock_state IN ('none', 'movement_locked', 'all_actions_locked')
                )
            );
            INSERT OR IGNORE INTO game_state (id, lock_state) VALUES (1, 'none');
            """
        )
        connection_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(room_connections)")
        }
        connection_migrations = {
            "has_lock": (
                "ALTER TABLE room_connections ADD COLUMN has_lock INTEGER "
                "NOT NULL DEFAULT 1 CHECK (has_lock IN (0, 1))"
            ),
            "is_locked": (
                "ALTER TABLE room_connections ADD COLUMN is_locked INTEGER "
                "NOT NULL DEFAULT 0 CHECK (is_locked IN (0, 1))"
            ),
            "is_broken": (
                "ALTER TABLE room_connections ADD COLUMN is_broken INTEGER "
                "NOT NULL DEFAULT 0 CHECK (is_broken IN (0, 1))"
            ),
            "is_open": (
                "ALTER TABLE room_connections ADD COLUMN is_open INTEGER "
                "NOT NULL DEFAULT 0 CHECK (is_open IN (0, 1))"
            ),
            "unlock_difficulty": (
                "ALTER TABLE room_connections ADD COLUMN unlock_difficulty INTEGER "
                "CHECK (unlock_difficulty BETWEEN 1 AND 30)"
            ),
            "has_trap": (
                "ALTER TABLE room_connections ADD COLUMN has_trap INTEGER "
                "NOT NULL DEFAULT 0 CHECK (has_trap IN (0, 1))"
            ),
            "trap_state": (
                "ALTER TABLE room_connections ADD COLUMN trap_state TEXT "
                "CHECK (trap_state IN ('armed', 'disarmed', 'triggered'))"
            ),
            "trap_detection_difficulty": (
                "ALTER TABLE room_connections ADD COLUMN "
                "trap_detection_difficulty INTEGER "
                "CHECK (trap_detection_difficulty BETWEEN 1 AND 30)"
            ),
            "trap_damage_type": (
                "ALTER TABLE room_connections ADD COLUMN trap_damage_type TEXT"
            ),
            "trap_damage": (
                "ALTER TABLE room_connections ADD COLUMN trap_damage INTEGER "
                "CHECK (trap_damage > 0)"
            ),
        }
        for column, statement in connection_migrations.items():
            if column not in connection_columns:
                connection.execute(statement)
        connection.execute(
            """
            UPDATE room_connections
            SET trap_state = 'armed'
            WHERE has_trap = 1 AND trap_state IS NULL
            """
        )
        # Existing areas become dungeons with one default floor.  Existing room
        # layouts are preserved and assigned to that floor.
        for area in connection.execute("SELECT id, name FROM areas").fetchall():
            floor_id = f"{area['id']}:floor:1"
            connection.execute(
                """
                INSERT OR IGNORE INTO dungeon_floors (id, dungeon_id, floor_number, name)
                VALUES (?, ?, 1, 'Floor 1')
                """,
                (floor_id, area["id"]),
            )
            connection.execute(
                "UPDATE rooms SET floor_id = ? WHERE area_id = ? AND floor_id IS NULL",
                (floor_id, area["id"]),
            )
        # Give legacy exits stable connection IDs without changing movement data.
        for exit_row in connection.execute(
            "SELECT room_id, name, destination_room_id FROM room_exits"
        ).fetchall():
            exists = connection.execute(
                """
                SELECT 1 FROM room_connections
                WHERE (from_room_id = ? AND exit_name = ? COLLATE NOCASE)
                   OR (to_room_id = ? AND return_exit_name = ? COLLATE NOCASE)
                """,
                (
                    exit_row["room_id"], exit_row["name"],
                    exit_row["room_id"], exit_row["name"],
                ),
            ).fetchone()
            if exists is None:
                connection.execute(
                    """
                    INSERT INTO room_connections (
                        id, from_room_id, to_room_id, exit_name, connection_type,
                        hidden, bidirectional
                    ) VALUES (?, ?, ?, ?, 'passage', 0, 0)
                    """,
                    (
                        uuid4().hex,
                        exit_row["room_id"],
                        exit_row["destination_room_id"],
                        exit_row["name"],
                    ),
                )
