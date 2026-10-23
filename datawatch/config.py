"""Configuration handling (a small JSON file in ``$XDG_CONFIG_HOME``)."""

from __future__ import annotations

import json
import os
from typing import Any

APP_NAME = "datawatch"

DEFAULTS: dict[str, Any] = {
    # Interfaces to count.  Empty list == "every interface except loopback".
    "interfaces": [],
    # Skip the loopback interface even in auto mode.
    "exclude_loopback": True,
    # Seconds between kernel counter reads.
    "poll_interval": 2.0,
    # Seconds of live graph history.
    "graph_window": 180,
    # How long per-minute samples are kept.
    "retention_days": 730,
    # Day of month the billing cycle restarts on (1-28 keeps every month sane).
    "cycle_day": 1,
    # Monthly / billing cycle allowance in GB.  0 disables the limit.
    "cycle_limit_gb": 0.0,
    # Daily allowance in GB.  0 disables the limit.
    "day_limit_gb": 0.0,
    # Fraction of a limit that triggers a warning, in percent.
    "warn_percent": 80.0,
    # Send desktop notifications.
    "notify": True,
    # Keep monitoring when the window is closed.
    "background_on_close": True,
    # "system", "light" or "dark"
    "color_scheme": "system",
}

_FLOAT_KEYS = {"poll_interval", "cycle_limit_gb", "day_limit_gb", "warn_percent"}
_INT_KEYS = {"retention_days", "cycle_day", "graph_window"}
_BOOL_KEYS = {"exclude_loopback", "notify", "background_on_close"}
_LIST_KEYS = {"interfaces"}
_STR_KEYS = {"color_scheme"}


def config_dir() -> str:
    override = os.environ.get("DATAWATCH_CONFIG_HOME")
    if override:
        return os.path.expanduser(override)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def data_dir() -> str:
    override = os.environ.get("DATAWATCH_DATA_HOME")
    if override:
        return os.path.expanduser(override)
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME)


def database_path() -> str:
    return os.path.join(data_dir(), "history.sqlite3")


class Config:
    """A flat bag of settings with sane defaults and validation."""

    def __init__(self, **values: Any):
        for key, default in DEFAULTS.items():
            setattr(self, key, values.get(key, default))
        self._coerce()
        self._validate()

    # -- class helpers ----------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        path = path or config_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError):
            # A broken config should never stop the monitor from running.
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {k: raw[k] for k in DEFAULTS if k in raw}
        return cls(**known)

    def save(self, path: str | None = None) -> None:
        path = path or config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {key: getattr(self, key) for key in DEFAULTS}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)

    # -- validation -------------------------------------------------------
    def _coerce(self) -> None:
        for key in _FLOAT_KEYS:
            try:
                setattr(self, key, float(getattr(self, key)))
            except (TypeError, ValueError):
                setattr(self, key, float(DEFAULTS[key]))
        for key in _INT_KEYS:
            try:
                setattr(self, key, int(float(getattr(self, key))))
            except (TypeError, ValueError):
                setattr(self, key, int(DEFAULTS[key]))
        for key in _BOOL_KEYS:
            setattr(self, key, bool(getattr(self, key)))
        for key in _LIST_KEYS:
            value = getattr(self, key)
            if not isinstance(value, list):
                value = list(DEFAULTS[key])
            setattr(self, key, [str(v) for v in value])
        for key in _STR_KEYS:
            value = getattr(self, key)
            if not isinstance(value, str) or value not in ("system", "light", "dark"):
                value = DEFAULTS[key]
            setattr(self, key, value)

    def _validate(self) -> None:
        self.poll_interval = min(60.0, max(1.0, self.poll_interval))
        self.graph_window = min(3600, max(30, self.graph_window))
        self.retention_days = min(36500, max(1, self.retention_days))
        self.cycle_day = min(28, max(1, self.cycle_day))
        self.warn_percent = min(100.0, max(1.0, self.warn_percent))
        self.cycle_limit_gb = max(0.0, self.cycle_limit_gb)
        self.day_limit_gb = max(0.0, self.day_limit_gb)

    # -- convenience ------------------------------------------------------
    def cycle_limit_bytes(self) -> int:
        return int(self.cycle_limit_gb * 1_000_000_000)

    def day_limit_bytes(self) -> int:
        return int(self.day_limit_gb * 1_000_000_000)
