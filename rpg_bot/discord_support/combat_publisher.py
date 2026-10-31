"""Discord combat presentation. The engine and SQLite log remain authoritative.

Turn summaries and current-map messages use stable IDs for retry recovery.
The publisher is the only component responsible for Discord combat posts.
"""

from __future__ import annotations

import asyncio
from hashlib import sha256
from io import BytesIO
import logging

import discord

from ..combat.models import CombatScene
from ..map_renderer.combat import render_combat_map
from .combat_events import (
    CombatEventReader, TURN_MARKERS, archive_embeds, closed_turns,
    current_turn_events,
)
from .combat_messages import CombatMessageStore


LOGGER = logging.getLogger(__name__)
COMBAT_CHANNEL_NAME = "combat"


def _field_text(lines: list[str], empty: str) -> str:
    value = "\n".join(lines) or empty
    return value if len(value) <= 1024 else value[:1021] + "..."


def combat_scene_embed(
    scene: CombatScene,
    room_name: str,
    image_filename: str = "combat-map.png",
    *,
    turn_marker_id: int = 0,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Combat · {room_name}",
        description="Choose **Actions** on your turn to move or fight.",
        colour=discord.Colour.from_rgb(111, 37, 32),
    )
    active = scene.current_combatant()
    if active is not None:
        embed.description = (
            f"**Round {scene.round_number}** · {active.name}'s turn. "
            "Use **Actions** to play."
        )
    order = [
        (
            f"{'▶ ' if active is not None and actor.kind == active.kind and actor.source_id == active.source_id else ''}"
            f"{actor.name} · Initiative {actor.initiative_score}"
        )
        for actor in scene.initiative_order()
    ]
    embed.add_field(
        name="Turn order", value=_field_text(order, "No combatants"),
        inline=False,
    )
    if active is not None:
        embed.add_field(
            name=f"Current turn · {active.name}"[:256],
            value=_field_text(
                [f"• {event}" for event in current_turn_events(scene)[-15:]],
                "Waiting for an action…",
            ),
            inline=False,
        )
    embed.set_image(url=f"attachment://{image_filename}")
    embed.set_footer(
        text=f"Scene #{scene.id} · Turn #{turn_marker_id} · active map"
    )
    return embed


async def ensure_combat_channel(guild):
    for channel in getattr(guild, "text_channels", ()):
        if getattr(channel, "name", "").casefold() == COMBAT_CHANNEL_NAME:
            return channel
    member = getattr(guild, "me", None)
    if member is None or not getattr(member.guild_permissions, "manage_channels", False):
        LOGGER.warning("Cannot create #combat in guild %s", getattr(guild, "id", "?"))
        return None
    try:
        return await guild.create_text_channel(
            COMBAT_CHANNEL_NAME,
            topic="Shared landmark-based combat scene and turn state.",
            reason="Public Rollkeeper combat channel",
        )
    except discord.HTTPException:
        LOGGER.exception("Cannot create #combat in guild %s", guild.id)
        return None


def _footer(message) -> str:
    embeds = getattr(message, "embeds", ())
    if not embeds:
        return ""
    return getattr(getattr(embeds[0], "footer", None), "text", "") or ""


class CombatPublisher:
    def __init__(self, service, world, store: CombatMessageStore, database_path, view_factory):
        self.service = service
        self.world = world
        self.store = store
        self.events = CombatEventReader(database_path)
        self.view_factory = view_factory
        self.messages = {}
        self.last_scenes = {}
        self.locks: dict[int, asyncio.Lock] = {}
        self._map_cache: dict[int, tuple[tuple, bytes]] = {}

    async def _find_message(self, guild, channel_id, message_id):
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        try:
            return await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _recent_message(self, channel, footer):
        """Recover an uploaded message after a crash before its SQLite commit."""
        if not hasattr(channel, "history"):
            return None
        try:
            async for candidate in channel.history(limit=150):
                if _footer(candidate) == footer:
                    return candidate
        except (discord.HTTPException, discord.Forbidden):
            LOGGER.exception("Could not reconcile Discord combat messages")
        return None

    async def _get_active(self, guild, saved):
        if saved is None:
            return None
        cached = self.messages.get(guild.id)
        if cached is not None and cached.id == saved.message_id:
            return cached
        return await self._find_message(guild, saved.channel_id, saved.message_id)

    async def _complete_turn(self, guild, channel, turn, original=None):
        pages = archive_embeds(turn)
        for index, embed in enumerate(pages, start=1):
            target = self.store.get_turn_page(
                turn.scene_id, turn.start_marker_id, index,
            )
            message = (
                await self._find_message(guild, *target) if target else None
            )
            if message is None and index == 1 and original is not None:
                # The old map may have been converted to a summary just
                # before the process stopped. Its footer is the recovery key.
                message = original
            if message is None:
                message = await self._recent_message(
                    channel, embed.footer.text,
                )
            if message is not None:
                if _footer(message) != embed.footer.text:
                    message = await message.edit(
                        embed=embed, view=None, attachments=[],
                    )
            else:
                message = await channel.send(
                    embed=embed, silent=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            self.store.save_turn_page(
                turn.scene_id, turn.start_marker_id, index,
                message.channel.id, message.id,
            )

    @staticmethod
    def _map_identity(scene):
        # The rendered image changes with layout, positions, and turn marker.
        # A full scene equality check allows cache reuse when only logs change.
        return (
            scene.id, scene.room_id, scene.round_number,
            scene.landmarks, scene.routes, scene.combatants,
            scene.current_turn_kind, scene.current_turn_source_id,
        )

    async def _map_image(self, scene, room_name):
        key = self._map_identity(scene)
        cached = self._map_cache.get(scene.guild_id)
        if cached is not None and cached[0] == key:
            return cached[1]
        rendered = await asyncio.to_thread(render_combat_map, scene, room_name)
        data = rendered.getvalue()
        self._map_cache[scene.guild_id] = (key, data)
        return data

    async def publish(self, guild, scene, *, channel=None):
        async with self.locks.setdefault(guild.id, asyncio.Lock()):
            channel = channel or await ensure_combat_channel(guild)
            if channel is None:
                return None
            latest = await asyncio.to_thread(self.service.current, guild.id)
            if latest is not None and latest.id == scene.id:
                scene = latest
            entries = await asyncio.to_thread(self.events.entries_from, scene.id, 0)
            markers = [entry for entry in entries if entry.event_type in TURN_MARKERS]
            current_marker = markers[-1].id if markers else 0
            active_footer = f"Scene #{scene.id} · Turn #{current_marker} · active map"

            saved = self.store.get(guild.id)
            if saved is not None and saved.scene_id != scene.id:
                saved = None
                self.messages.pop(guild.id, None)
            previous = await self._get_active(guild, saved)
            if saved is not None and saved.turn_marker_id == 0:
                # Upgrade the original single-map pointer without replaying
                # historical turns or creating a duplicate.
                self.store.save(
                    guild.id, scene.id, saved.channel_id, saved.message_id,
                    current_marker,
                )
                saved = self.store.get(guild.id)

            if saved is not None and saved.turn_marker_id != current_marker:
                completed = closed_turns(
                    [entry for entry in entries if entry.id >= saved.turn_marker_id],
                    scene.id,
                )
                try:
                    for index, turn in enumerate(completed):
                        await self._complete_turn(
                            guild, channel, turn,
                            original=previous if index == 0 else None,
                        )
                except discord.HTTPException:
                    LOGGER.exception("Cannot finalize combat turn in guild %s", guild.id)
                    return None
                previous = None
                self.messages.pop(guild.id, None)

            if previous is None:
                previous = await self._recent_message(channel, active_footer)

            room = self.world.get_room(scene.room_id)
            room_name = room.name if room is not None else scene.room_id
            try:
                image_bytes = await self._map_image(scene, room_name)
                filename = f"combat-map-{sha256(image_bytes).hexdigest()[:12]}.png"
                embed = combat_scene_embed(
                    scene, room_name, filename, turn_marker_id=current_marker,
                )
                file = discord.File(BytesIO(image_bytes), filename=filename)
                if previous is not None:
                    result = await previous.edit(
                        embed=embed, view=self.view_factory(scene.id),
                        attachments=[file],
                    )
                else:
                    result = await channel.send(
                        embed=embed, view=self.view_factory(scene.id),
                        file=file, silent=True,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                self.messages[guild.id] = result
                self.store.save(
                    guild.id, scene.id,
                    result.channel.id, result.id, current_marker,
                )
                self.last_scenes[guild.id] = scene
                return channel
            except discord.HTTPException:
                LOGGER.exception("Could not publish combat map in guild %s", guild.id)
                return None
            except Exception:
                LOGGER.exception("Combat map rendering failed in guild %s", guild.id)
                return None

    async def end(self, guild, previous):
        async with self.locks.setdefault(guild.id, asyncio.Lock()):
            saved = self.store.get(guild.id)
            if saved is not None and saved.scene_id == previous.id:
                entries = await asyncio.to_thread(
                    self.events.entries_from, previous.id, 0,
                )
                last_marker = saved.turn_marker_id or next(
                    (e.id for e in reversed(entries) if e.event_type in TURN_MARKERS), 0
                )
                closed = closed_turns(
                    [e for e in entries if e.id >= last_marker], previous.id,
                )
                message = await self._get_active(guild, saved)
                if closed:
                    try:
                        channel = await ensure_combat_channel(guild)
                        if channel is not None:
                            for i, turn in enumerate(closed):
                                await self._complete_turn(
                                    guild, channel, turn,
                                    original=message if i == 0 else None,
                                )
                    except discord.HTTPException:
                        LOGGER.exception("Combat final turn could not be archived")
                        return
                elif message is not None:
                    try:
                        await message.edit(
                            embed=discord.Embed(title="Combat ended"),
                            view=None, attachments=[],
                        )
                    except discord.HTTPException:
                        LOGGER.exception("Combat final card could not be closed")
                        return
            self.store.clear(guild.id)
            self.messages.pop(guild.id, None)
            self.last_scenes.pop(guild.id, None)
            self._map_cache.pop(guild.id, None)
