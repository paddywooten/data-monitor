"""PyInstaller entry point for the frozen builds.

Built by build-windows.bat (Windows .exe) or build-mac.sh (macOS .app /
.dmg).  ``datamonitor.entry.run()`` provides the D-Bus / single-instance
bootstrap a frozen build needs, then hands over to the normal main().
"""

import sys

from datamonitor.entry import run

if __name__ == "__main__":
    raise SystemExit(run())
