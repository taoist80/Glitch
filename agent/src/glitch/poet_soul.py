"""Load Poet personality from poet-soul.md.

Poet is a creative writing sub-agent with a separate soul file.
Searches: agent/poet-soul.md, /app/poet-soul.md, ~/poet-soul.md.
S3 can be added later for parity with Glitch SOUL.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_default_poet_soul_path() -> Path:
    """Return the default path for poet-soul.md (agent directory)."""
    # From agent/src/glitch/poet_soul.py -> agent/src/glitch -> agent/src -> agent
    return Path(__file__).parent.parent.parent / "poet-soul.md"


def load_poet_soul() -> str:
    """Load Poet personality from poet-soul.md.

    Search order:
    1. agent/poet-soul.md (development)
    2. /app/poet-soul.md (container)
    3. ~/poet-soul.md (fallback)

    Returns:
        Contents of poet-soul.md or empty string if not found.
    """
    soul_paths = [
        get_default_poet_soul_path(),
        Path("/app/poet-soul.md"),
        Path.home() / "poet-soul.md",
    ]
    for path in soul_paths:
        if path.exists():
            logger.info("Loading Poet soul from %s", path)
            return path.read_text()
    logger.warning("poet-soul.md not found, using default Poet personality")
    return ""
