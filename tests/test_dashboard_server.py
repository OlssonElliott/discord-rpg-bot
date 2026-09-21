from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from rpg_bot.dashboard_api import DashboardAPI
from rpg_bot.dashboard_server import DashboardRequestHandler, main
from rpg_bot.database import Database
from rpg_bot.inventory import ItemCatalog
from rpg_bot.room_images import RoomImageStore
from rpg_bot.world_service import WorldService


class QuietDashboardRequestHandler(DashboardRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class DashboardServerConfigurationTests(unittest.TestCase):
    def test_main_loads_dotenv_before_dashboard_configuration(self) -> None:
        server = Mock()

        def populate_environment() -> bool:
            os.environ["DATABASE_PATH"] = "configured-dashboard.db"
            os.environ["DISCORD_GUILD_ID"] = "987654321"
            os.environ["CHARACTER_MEDIA_PATH"] = "configured-characters"
            return True

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(sys, "argv", ["dashboard_server"]),
            patch(
                "rpg_bot.dashboard_server.load_dotenv",
                side_effect=populate_environment,
            ) as load_environment,
            patch("rpg_bot.dashboard_server.Database") as database_type,
            patch("rpg_bot.dashboard_server.WorldService") as world_service_type,
            patch(
                "rpg_bot.dashboard_server.CharacterPortraitStore"
            ) as portrait_store_type,
            patch("rpg_bot.dashboard_server.DashboardAPI") as dashboard_api_type,
            patch(
                "rpg_bot.dashboard_server.ThreadingHTTPServer",
                return_value=server,
            ),
        ):
            main()

        load_environment.assert_called_once_with()
        database_type.assert_called_once_with("configured-dashboard.db")
        database_type.return_value.initialize.assert_called_once_with()
        world_service_type.assert_called_once_with(database_type.return_value)
        portrait_store_type.assert_called_once_with(
            "configured-characters"
        )
        dashboard_api_type.assert_called_once_with(
            world_service_type.return_value,
            portraits=portrait_store_type.return_value,
            guild_id=987654321,
        )
        server.serve_forever.assert_called_once_with()


class DashboardServerRoomImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        database = Database(root / "dashboard.db")
        database.initialize()
        catalog_path = root / "items.json"
        catalog_path.write_text("[]\n", encoding="utf-8")
        world = WorldService(database, ItemCatalog.load(catalog_path))
        world.create_area("crypt", "Crypt")
        world.create_room("hall", "crypt", "Hall", editor_x=0, editor_y=0)
        QuietDashboardRequestHandler.api = DashboardAPI(
            world, RoomImageStore(root / "room_images")
        )
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), QuietDashboardRequestHandler
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def test_binary_room_image_upload_get_and_delete(self) -> None:
        output = BytesIO()
        Image.new("RGB", (640, 360), "purple").save(output, format="PNG")
        connection = HTTPConnection(*self.server.server_address, timeout=5)

        connection.request(
            "POST",
            "/api/rooms/hall/image",
            body=output.getvalue(),
            headers={"Content-Type": "image/png", "X-File-Name": "hall.png"},
        )
        upload = connection.getresponse()
        upload_payload = json.loads(upload.read())
        self.assertEqual(upload.status, 200)
        self.assertIn("version=", upload_payload["room_image_url"])

        connection.request("GET", upload_payload["room_image_url"])
        download = connection.getresponse()
        downloaded_image = download.read()
        self.assertEqual(download.status, 200)
        self.assertEqual(download.getheader("Content-Type"), "image/webp")
        with Image.open(BytesIO(downloaded_image)) as stored:
            self.assertEqual(stored.format, "WEBP")

        connection.request("DELETE", "/api/rooms/hall/image")
        removed = connection.getresponse()
        removed.read()
        self.assertEqual(removed.status, 200)

        connection.request("GET", "/api/rooms/hall/image")
        missing = connection.getresponse()
        missing.read()
        self.assertEqual(missing.status, 404)
        connection.close()


if __name__ == "__main__":
    unittest.main()
