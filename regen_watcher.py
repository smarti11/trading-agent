"""Rebuilds dashboard.html every 5 minutes by running dashboard.py as a subprocess.

Run alongside agent.py and the HTTP server. Path resolution uses
Path(__file__).parent so the script is cwd-independent.
"""

import logging
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent

# Structured log goes to logs/regen.log; stdout is captured by nohup → logs/regen.out
log_path = ROOT / "logs" / "regen.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(str(log_path)),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

DASHBOARD_SCRIPT = ROOT / "dashboard.py"
REBUILD_INTERVAL_S = 5 * 60  # 5 minutes
SUBPROCESS_TIMEOUT_S = 60    # dashboard.py reads live prices; 60 s is generous


def rebuild() -> bool:
    """Run dashboard.py as a subprocess. Returns True on success."""
    try:
        result = subprocess.run(
            [sys.executable, str(DASHBOARD_SCRIPT)],
            cwd=str(ROOT),           # so DB_PATH="db/trades.db" resolves correctly
            timeout=SUBPROCESS_TIMEOUT_S,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("Dashboard rebuilt OK")
            return True
        logger.error(
            "dashboard.py exited %d: %s",
            result.returncode,
            result.stderr.strip()[:300] or result.stdout.strip()[:300],
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("dashboard.py timed out after %ds — killed", SUBPROCESS_TIMEOUT_S)
        return False
    except Exception as e:
        logger.error("Rebuild failed: %s", e, exc_info=True)
        return False


def main():
    logger.info("Trading regen watcher starting")
    logger.info("Script: %s", DASHBOARD_SCRIPT)
    logger.info("Rebuild interval: %d min", REBUILD_INTERVAL_S // 60)

    # Immediate build at startup so there's no cold-start wait
    logger.info("Initial build")
    rebuild()

    while True:
        time.sleep(REBUILD_INTERVAL_S)
        logger.info("Periodic rebuild (%dmin)", REBUILD_INTERVAL_S // 60)
        rebuild()


if __name__ == "__main__":
    main()
