"""Discord adapter for the player-specific dungeon HUD."""

from pathlib import Path
import re

import discord

from .database import Database
from .dungeon import KnowledgeState, PlayerMap
from .map_renderer import render_player_map
from .player_view_service import PlayerViewService


def private_map_channel_name(character_name: str, character_id: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", character_name.casefold()).strip("-")
    return f"map-{slug or character_id}"[:100]


class DiscordPlayerViewAdapter:
    """Render a filtered map and send/edit its single Discord message."""

    def __init__(
        self,
        database: Database,
        views: PlayerViewService,
        client: discord.Client,
    ) -> None:
        self.database = database
        self.views = views
        self.client = client

    async def edit_view_message(
        self, channel_id: int, message_id: int, view: PlayerMap
    ) -> bool:
        channel = await self._channel(channel_id)
        if channel is None or not hasattr(channel, "fetch_message"):
            return False
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return False
        await self.edit_message(message, view)
        return True

    async def create_view_message(self, channel_id: int, view: PlayerMap) -> int:
        channel = await self._channel(channel_id)
        if channel is None or not hasattr(channel, "send"):
            raise ValueError("The private map channel no longer exists.")
        embeds, files, controls = self._message_parts(view)
        message = await channel.send(embeds=embeds, files=files, view=controls)
        return message.id

    async def edit_message(self, message: discord.Message, view: PlayerMap) -> None:
        embeds, files, controls = self._message_parts(view)
        await message.edit(embeds=embeds, attachments=files, view=controls)

    def controls(self, view: PlayerMap) -> "DungeonMapControls":
        owner_id = next(
            character.discord_user_id
            for character in self.database.list_all_characters()
            if character.character_id == view.character_id
        )
        return DungeonMapControls(self, view, owner_id)

    def _message_parts(
        self, view: PlayerMap
    ) -> tuple[list[discord.Embed], list[discord.File], "DungeonMapControls"]:
        map_file = discord.File(render_player_map(view), filename="dungeon-map.png")
        files = [map_file]
        dungeon = self.database.get_dungeon(view.dungeon_id)
        dungeon_name = dungeon.name if dungeon is not None else view.dungeon_id
        map_embed = discord.Embed(
            title=f"✦ {dungeon_name} · {view.floor.name} ✦",
            description=(
                "**Gold** marks where you stand. **Bone** marks what you inspect.\n"
                "Dashed chambers remain unvisited."
            ),
            colour=discord.Colour.from_rgb(154, 120, 61),
        )
        map_embed.set_image(url="attachment://dungeon-map.png")
        if view.current_room_id and not any(room.is_current for room in view.rooms):
            map_embed.set_footer(text="Your character is currently on another floor.")
        elif view.focused_room_id != view.current_room_id:
            map_embed.set_footer(
                text="Inspected room differs from your current location."
            )

        embeds = [map_embed]
        if view.focused_room is not None:
            focused = view.focused_room
            is_current = focused.room_id == view.current_room_id
            if focused.knowledge_state is KnowledgeState.KNOWN:
                room_embed = discord.Embed(
                    title=f"? {focused.name}",
                    description=(
                        "*A place marked on your map, but not yet present in "
                        "your memories.*"
                    ),
                    colour=discord.Colour.from_rgb(91, 78, 59),
                )
                room_embed.set_author(name="KNOWN · UNVISITED")
                room_embed.add_field(
                    name="Journal",
                    value="Not personally visited.",
                    inline=False,
                )
                room_embed.set_footer(text="No visual memory recorded.")
            else:
                room_embed = discord.Embed(
                    title=focused.name,
                    description=(focused.description or "No saved description.")[:2000],
                    colour=(
                        discord.Colour.from_rgb(111, 37, 32)
                        if is_current
                        else discord.Colour.from_rgb(154, 120, 61)
                    ),
                )
                room_embed.set_author(
                    name="CURRENT ROOM" if is_current else "INSPECTED ROOM"
                )
                room_embed.add_field(
                    name="Journal",
                    value=(
                        "You are here."
                        if is_current
                        else "Visited · Recalled from your travels."
                    ),
                    inline=False,
                )
                if focused.visible_characters:
                    room_embed.add_field(
                        name="Characters",
                        value="\n".join(focused.visible_characters),
                        inline=True,
                    )
                if focused.visible_entities:
                    room_embed.add_field(
                        name="Visible",
                        value="\n".join(focused.visible_entities),
                        inline=True,
                    )
                if focused.visible_items:
                    room_embed.add_field(
                        name="Items",
                        value="\n".join(focused.visible_items),
                        inline=True,
                    )
                if focused.scene_image_url:
                    room_embed.set_image(url=focused.scene_image_url)
                    room_embed.set_footer(text="Visual memory")
                elif focused.scene_image_path:
                    scene_path = Path(focused.scene_image_path)
                    if scene_path.is_file():
                        filename = f"room-scene{scene_path.suffix or '.png'}"
                        files.append(discord.File(scene_path, filename=filename))
                        room_embed.set_image(url=f"attachment://{filename}")
                        room_embed.set_footer(text="Visual memory")
                    else:
                        room_embed.set_footer(
                            text="The remembered scene is currently unavailable."
                        )
            embeds.append(room_embed)
        return embeds, files, self.controls(view)

    async def _channel(self, channel_id: int):
        channel = self.client.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await self.client.fetch_channel(channel_id)
        except discord.NotFound:
            return None


class DungeonMapControls(discord.ui.View):
    def __init__(
        self,
        adapter: DiscordPlayerViewAdapter,
        view: PlayerMap,
        owner_id: int,
    ) -> None:
        super().__init__(timeout=None)
        self.adapter = adapter
        self.character_id = view.character_id
        self.owner_id = owner_id

        known_floor_ids = {
            room.floor_id
            for knowledge in adapter.database.list_character_knowledge(view.character_id)
            if (room := adapter.database.get_room(knowledge.room_id)) is not None
            and room.floor_id is not None
        }
        floors = [
            floor
            for floor in adapter.database.list_floors(view.dungeon_id)
            if floor.id in known_floor_ids
        ][:25]
        if len(floors) > 1:
            floor_select = discord.ui.Select(
                placeholder="Choose a known floor",
                options=[
                    discord.SelectOption(
                        label=floor.name[:100],
                        value=floor.id,
                        description=f"Floor {floor.floor_number}"[:100],
                        default=floor.id == view.floor.id,
                    )
                    for floor in floors
                ],
                custom_id=f"dungeon-map:floor:{view.character_id}",
                row=0,
            )
            floor_select.callback = self._floor_changed
            self.add_item(floor_select)

        if view.rooms:
            room_select = discord.ui.Select(
                placeholder="Inspect room",
                options=[
                    discord.SelectOption(
                        label=room.display_name[:100],
                        value=room.id,
                        description=(
                            "Visited" if room.knowledge_state is KnowledgeState.VISITED
                            else "Known, not visited"
                        ),
                        default=room.is_focused,
                    )
                    for room in view.rooms[:25]
                ],
                custom_id=f"dungeon-map:room:{view.character_id}",
                row=1,
            )
            room_select.callback = self._room_changed
            self.add_item(room_select)

        refresh = discord.ui.Button(
            label="Consult map",
            style=discord.ButtonStyle.secondary,
            custom_id=f"dungeon-map:refresh:{view.character_id}",
            row=2,
        )
        refresh.callback = self._refresh
        self.add_item(refresh)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "This map belongs to another character.", ephemeral=True
        )
        return False

    async def _floor_changed(self, interaction: discord.Interaction) -> None:
        selected = interaction.data.get("values", [None])[0]
        if selected is None:
            return
        self.adapter.views.select_floor(self.character_id, selected)
        await self._replace(interaction)

    async def _room_changed(self, interaction: discord.Interaction) -> None:
        selected = interaction.data.get("values", [None])[0]
        if selected is None:
            return
        self.adapter.views.focus_room(self.character_id, selected)
        await self._replace(interaction)

    async def _refresh(self, interaction: discord.Interaction) -> None:
        await self._replace(interaction)

    async def _replace(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = self.adapter.views.build_player_map(self.character_id)
        if interaction.message is not None:
            await self.adapter.edit_message(interaction.message, view)
