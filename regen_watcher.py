"""Rebuilds dashboard.html and options_dashboard.html every 5 minutes by
running dashboard.py / options_dashboard.py as subprocesses.

Run alongside agent.py, options_agent.py, and the HTTP server. Path
resolution uses Path(__file__).parent so the script is cwd-independent.
"""

import logging
import subprocess
import sys
import time
from pathlib import Path

from core.risk import RiskManager

ROOT = Path(__file__).parent

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

DASHBOARD_SCRIPTS = [ROOT / "dashboard.py", ROOT / "options_dashboard.py"]
REBUILD_INTERVAL_S = 5 * 60
SUBPROCESS_TIMEOUT_S = 60


def rebuild(script: Path) -> bool:
    """Run the given dashboard script as a subprocess. Returns True on success."""
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            timeout=SUBPROCESS_TIMEOUT_S,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("%s rebuilt OK", script.name)
            return True
        logger.error(
            "%s exited %d: %s",
            script.name,
            result.returncode,
            result.stderr.strip()[:300] or result.stdout.strip()[:300],
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("%s timed out after %ds — killed", script.name, SUBPROCESS_TIMEOUT_S)
        return False
    except Exception as e:
        logger.error("Rebuild of %s failed: %s", script.name, e, exc_info=True)
        return False


def rebuild_all():
    for script in DASHBOARD_SCRIPTS:
        rebuild(script)


def main():
    logger.info("Trading regen watcher starting")
    logger.info("Scripts: %s", ", ".join(s.name for s in DASHBOARD_SCRIPTS))
    logger.info("Rebuild interval: %d min", REBUILD_INTERVAL_S // 60)

    risk = RiskManager()

    logger.info("Initial build")
    rebuild_all()

    while True:
        time.sleep(REBUILD_INTERVAL_S)
        if not risk.is_market_open():
            logger.info("Market closed — skipping dashboard rebuild")
            continue
        logger.info("Periodic rebuild (%dmin)", REBUILD_INTERVAL_S // 60)
        rebuild_all()


if __name__ == "__main__":
    main()
