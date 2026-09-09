"""Start the dashboard API with the project's portable Python runtime."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_PACKAGES = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"

if not SITE_PACKAGES.is_dir():
    raise SystemExit(
        "Missing .venv/Lib/site-packages. Install the Python dependencies first."
    )

sys.path.insert(0, str(SITE_PACKAGES))
sys.path.insert(0, str(PROJECT_ROOT))

from rpg_bot.dashboard_server import main


if __name__ == "__main__":
    main()
