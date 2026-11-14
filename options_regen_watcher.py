"""Rebuilds options_dashboard.html every 5 minutes during market hours."""

import logging
import subprocess
import sys
import time
from pathlib import Path

from core.options.risk import OptionsRiskManager

ROOT = Path(__file__).parent
log_path = ROOT / "logs" / "options_regen.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(log_path)),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

DASHBOARD_SCRIPT = ROOT / "options_dashboard.py"
REBUILD_INTERVAL_S = 5 * 60
SUBPROCESS_TIMEOUT_S = 90


def rebuild() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, str(DASHBOARD_SCRIPT)],
            cwd=str(ROOT),
            timeout=SUBPROCESS_TIMEOUT_S,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("Options dashboard rebuilt OK")
            return True
        logger.error(
            "options_dashboard.py exited %d: %s",
            result.returncode,
            result.stderr.strip()[:300] or result.stdout.strip()[:300],
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("options_dashboard.py timed out after %ds", SUBPROCESS_TIMEOUT_S)
        return False
    except Exception as e:
        logger.error("Rebuild failed: %s", e, exc_info=True)
        return False


def main():
    logger.info("Options regen watcher starting")
    risk = OptionsRiskManager()
    rebuild()
    while True:
        time.sleep(REBUILD_INTERVAL_S)
        if not risk.is_market_open():
            logger.info("Market closed — skipping options dashboard rebuild")
            continue
        logger.info("Periodic options dashboard rebuild")
        rebuild()


if __name__ == "__main__":
    main()
