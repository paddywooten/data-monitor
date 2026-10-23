"""Data Monitor - an internet data usage monitor for your laptop.

Tracks per-interface download/upload traffic from the OS counters (Linux
``/proc/net/dev``, Windows / macOS via psutil - no root, no packet
capture), attributes traffic to programs via TCP socket counters
(``ss`` on Linux), stores history in SQLite and shows a live
GTK4/libadwaita dashboard with quota alerts and per-app / overall data
restrictions.

Linux is the reference platform; the packaged Windows / macOS builds
(see the build scripts at the repository root) cover totals, history,
quotas and the overall cap.
"""

APP_NAME = "Data Monitor"
APP_ID = "io.datamonitor.App"
__version__ = "1.3.0"
