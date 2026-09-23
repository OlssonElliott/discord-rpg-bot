"""Local HTTP server joining the DM dashboard to the game database."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

from .api import DashboardAPI
from ..database import Database
from ..media.portraits import CharacterPortraitStore, MAX_PORTRAIT_BYTES
from ..media.room_images import MAX_ROOM_IMAGE_BYTES
from ..world.service import WorldService


class DashboardRequestHandler(BaseHTTPRequestHandler):
    api: DashboardAPI

    def _send_json(self, status: int, payload: object) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def _handle_api(self) -> None:
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        image_match = re.fullmatch(r"/api/rooms/([^/]+)/image", path)
        if self.command == "POST" and image_match:
            if length > MAX_ROOM_IMAGE_BYTES:
                self.close_connection = True
                self._send_json(413, {"error": "Room images may be at most 8 MB."})
                return
            status, payload = self.api.upload_room_image(
                unquote(image_match.group(1)),
                self.rfile.read(length),
                self.headers.get("Content-Type", ""),
                unquote(self.headers.get("X-File-Name", "")) or None,
            )
            self._send_json(status, payload)
            return

        portrait_match = re.fullmatch(
            r"/api/characters/([1-9][0-9]*)/portrait",
            path,
        )
        if self.command == "POST" and portrait_match:
            if length > MAX_PORTRAIT_BYTES:
                self.close_connection = True
                self._send_json(413, {"error": "Portraits may be at most 5 MB."})
                return
            status, payload = self.api.upload_character_portrait(
                int(portrait_match.group(1)),
                self.rfile.read(length),
            )
            self._send_json(status, payload)
            return
        try:
            body: dict[str, Any] = (
                json.loads(self.rfile.read(length)) if length else {}
            )
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object.")
            status, payload = self.api.handle(self.command, path, body)
        except (json.JSONDecodeError, ValueError) as error:
            status, payload = 400, {"error": str(error)}
        self._send_json(status, payload)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        image_match = re.fullmatch(r"/api/rooms/([^/]+)/image", path)
        if image_match:
            image_path = self.api.room_image_path(unquote(image_match.group(1)))
            if image_path is None:
                self._send_json(404, {"error": "Room image not found."})
                return
            content = image_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/webp")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)
            return

        portrait_match = re.fullmatch(
            r"/api/characters/([1-9][0-9]*)/portrait",
            path,
        )
        if portrait_match:
            portrait_path = self.api.character_portrait_path(
                int(portrait_match.group(1))
            )
            if portrait_path is None:
                self._send_json(404, {"error": "Character portrait not found."})
                return
            content = portrait_path.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "image/png" if portrait_path.suffix.casefold() == ".png" else "image/webp",
            )
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)
        elif path.startswith("/api/"):
            self._handle_api()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        self._handle_api()

    def do_PUT(self) -> None:
        self._handle_api()

    def do_PATCH(self) -> None:
        self._handle_api()

    def do_DELETE(self) -> None:
        self._handle_api()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, X-File-Name"
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.end_headers()


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run the local RPG DM dashboard API.")
    parser.add_argument(
        "--database",
        default=os.getenv("DATABASE_PATH", "rpg_bot.db"),
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--guild-id",
        type=int,
        default=None,
        help="Discord guild whose combat state the dashboard controls.",
    )
    arguments = parser.parse_args()

    guild_id = arguments.guild_id
    if guild_id is None:
        configured_guild = os.getenv("DISCORD_GUILD_ID", "").strip()
        if configured_guild:
            try:
                guild_id = int(configured_guild)
            except ValueError as error:
                raise ValueError("DISCORD_GUILD_ID must be numeric.") from error

    database = Database(arguments.database)
    database.initialize()
    DashboardRequestHandler.api = DashboardAPI(
        WorldService(database),
        portraits=CharacterPortraitStore(
            os.getenv("CHARACTER_MEDIA_PATH", "data/characters")
        ),
        guild_id=guild_id,
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", arguments.port), DashboardRequestHandler
    )
    print(f"DM dashboard API listening on http://localhost:{arguments.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
