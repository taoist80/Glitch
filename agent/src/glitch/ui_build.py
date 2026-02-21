"""UI build utilities for Glitch agent.

Shared helper for auto-building the UI from both __main__.py and server.py.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_ui_paths() -> tuple[Path, Path]:
    """Return (ui_dir, ui_dist) paths based on repo layout.
    
    Returns:
        Tuple of (ui source directory, ui dist directory)
    """
    # This file: agent/src/glitch/ui_build.py -> glitch -> src -> agent -> repo root
    agent_dir = Path(__file__).resolve().parent.parent.parent
    repo_root = agent_dir.parent
    ui_dir = repo_root / "ui"
    ui_dist = ui_dir / "dist"
    return ui_dir, ui_dist


def auto_build_ui(ui_dir: Optional[Path] = None, verbose: bool = False) -> bool:
    """Build the UI automatically using pnpm if available.
    
    Args:
        ui_dir: Path to the ui/ directory containing package.json (auto-detected if None)
        verbose: If True, print progress to stdout; otherwise use logging
    
    Returns:
        True if build succeeded or dist already exists, False on failure
    """
    if ui_dir is None:
        ui_dir, ui_dist = get_ui_paths()
    else:
        ui_dist = ui_dir / "dist"

    if ui_dist.is_dir():
        return True  # Already built

    if not ui_dir.is_dir():
        return False  # No UI source

    pnpm = shutil.which("pnpm")
    if not pnpm:
        msg = "pnpm not found; cannot auto-build UI. Install pnpm or run 'cd ui && pnpm build' manually."
        if verbose:
            print(f"⚠️  {msg}")
        else:
            logger.warning(msg)
        return False

    msg = f"UI dist not found; auto-building UI from {ui_dir} ..."
    if verbose:
        print(f"🔨 Building UI (first run)...")
    else:
        logger.info(msg)

    try:
        # Install deps if node_modules missing
        if not (ui_dir / "node_modules").is_dir():
            if verbose:
                print("   Installing dependencies...")
            else:
                logger.info("Installing UI dependencies...")
            subprocess.run([pnpm, "install"], cwd=str(ui_dir), check=True, capture_output=True)
        
        # Build
        subprocess.run([pnpm, "build"], cwd=str(ui_dir), check=True, capture_output=True)
        
        if verbose:
            print("✅ UI built successfully")
        else:
            logger.info("UI build completed successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        msg = f"UI build failed: {stderr[:500] or str(e)}"
        if verbose:
            print(f"❌ {msg[:300]}")
        else:
            logger.error(msg)
        return False
    except Exception as e:
        msg = f"UI auto-build error: {e}"
        if verbose:
            print(f"❌ {msg}")
        else:
            logger.error(msg)
        return False
