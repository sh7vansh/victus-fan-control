"""Project paths and metadata shared by packaging scripts."""

from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOURCE))

from fan_control import APP_ID, LEGACY_APP_ID, __version__
