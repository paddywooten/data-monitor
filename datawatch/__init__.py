"""Datawatch - an internet data usage monitor for your laptop.

Tracks per-interface download/upload traffic from the kernel counters in
``/proc/net/dev`` (no root required), stores history in SQLite and shows
a live GTK4/libadwaita dashboard with quota alerts.
"""

APP_NAME = "Datawatch"
APP_ID = "io.datawatch.App"
__version__ = "1.1.0"
