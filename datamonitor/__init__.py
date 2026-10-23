"""Data Monitor - an internet data usage monitor for your laptop.

Tracks per-interface download/upload traffic from the kernel counters in
``/proc/net/dev`` (no root required), attributes traffic to programs via
TCP socket counters (``ss``, no packet capture), stores history in SQLite
and shows a live GTK4/libadwaita dashboard with quota alerts and
per-app / overall data restrictions.
"""

APP_NAME = "Data Monitor"
APP_ID = "io.datamonitor.App"
__version__ = "1.2.0"
