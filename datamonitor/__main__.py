"""``python -m datamonitor`` entry point."""

from __future__ import annotations

import argparse
import sys

from . import APP_NAME, __version__
from .application import DataMonitorApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="datamonitor",
        description=f"{APP_NAME} - internet data usage monitor",
    )
    parser.add_argument(
        "--version", action="version", version=f"{APP_NAME} {__version__}"
    )
    parser.add_argument(
        "--hidden",
        action="store_true",
        help="start in the background without showing the window",
    )
    parser.add_argument(
        "--page",
        choices=("overview", "history", "apps", "interfaces"),
        help="open the dashboard on a specific tab",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="open the preferences dialog on start",
    )
    args, rest = parser.parse_known_args(argv)

    app = DataMonitorApp(
        start_hidden=args.hidden,
        start_page=args.page,
        open_settings=args.settings,
    )
    return app.run([sys.argv[0]] + rest)


if __name__ == "__main__":
    raise SystemExit(main())
