"""pytest configuration — ensure the plugin package is importable."""

import sys
from pathlib import Path

# Add repo root (this directory's parent) to sys.path so that `import
# web_to_obsidian` resolves to web_to_obsidian.py. Tests live next to the
# plugin package, so parents[1] IS the repository root (the plugin package).
_plugin_dir = str(Path(__file__).resolve().parents[1])
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)
