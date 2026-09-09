"""Local HTTP server joining the DM dashboard to the game database."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any

from .dashboard_api import DashboardAPI
from .database import Database
from .world_service import WorldService


class DashboardRequestHandler(BaseHTTPRequestHandler):
    api: DashboardAPI

    def _handle_api(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body: dict[str, Any] = (
                json.loads(self.rfile.read(length)) if length else {}
            )
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object.")
            status, payload = self.api.handle(self.command, self.path, body)
        except (json.JSONDecodeError, ValueError) as error:
            status, payload = 400, {"error": str(error)}
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self._handle_api()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        self._handle_api()

    def do_PATCH(self) -> None:
        self._handle_api()

    def do_DELETE(self) -> None:
        self._handle_api()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local RPG DM dashboard API.")
    parser.add_argument("--database", default="rpg_bot.db")
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args()

    database = Database(arguments.database)
    database.initialize()
    DashboardRequestHandler.api = DashboardAPI(WorldService(database))
    server = ThreadingHTTPServer(
        ("127.0.0.1", arguments.port), DashboardRequestHandler
    )
    print(f"DM dashboard API listening on http://localhost:{arguments.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
