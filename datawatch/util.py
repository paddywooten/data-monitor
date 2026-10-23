"""Small formatting / time helpers shared across the app."""

from __future__ import annotations

import calendar
import time

# Data volumes are shown in decimal (SI) units because ISP / mobile quotas
# are almost always quoted that way: 1 GB = 1_000_000_000 bytes.
_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")
_RATE_UNITS = ("bps", "kbps", "Mbps", "Gbps", "Tbps")


def format_bytes(n: float, precision: int | None = None) -> str:
    """Human readable byte size, e.g. ``1.24 GB``."""
    value = float(max(0.0, n))
    i = 0
    while value >= 1000.0 and i < len(_SIZE_UNITS) - 1:
        value /= 1000.0
        i += 1
    if i == 0:
        return f"{int(round(value))} {_SIZE_UNITS[0]}"
    if precision is None:
        precision = 2 if value < 10 else (1 if value < 100 else 0)
    return f"{value:.{precision}f} {_SIZE_UNITS[i]}"


def format_rate(bits_per_second: float, precision: int | None = None) -> str:
    """Human readable bitrate, e.g. ``3.42 Mbps``."""
    value = float(max(0.0, bits_per_second))
    i = 0
    while value >= 1000.0 and i < len(_RATE_UNITS) - 1:
        value /= 1000.0
        i += 1
    if i == 0:
        return f"{int(round(value))} {_RATE_UNITS[0]}"
    if precision is None:
        precision = 2 if value < 10 else (1 if value < 100 else 0)
    return f"{value:.{precision}f} {_RATE_UNITS[i]}"


def format_percent(fraction: float, precision: int = 1) -> str:
    return f"{max(0.0, fraction) * 100:.{precision}f}%"


def format_bytes_parts(n: float) -> tuple[str, str]:
    """Return ``(number, unit)`` so widgets can style them separately."""
    text = format_bytes(n)
    number, _, unit = text.rpartition(" ")
    return number, unit


# --------------------------------------------------------------------------
# local-time day / month boundaries (DST safe)
# --------------------------------------------------------------------------

def start_of_day(ts: float) -> int:
    t = time.localtime(ts)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def add_days(ts: float, days: int) -> int:
    """Advance ``days`` whole local days (anchored at noon to survive DST)."""
    t = time.localtime(ts)
    total = t.tm_mday + days
    year, month = t.tm_year, t.tm_mon
    days_in_month = calendar.monthrange(year, month)[1]
    while total > days_in_month:
        total -= days_in_month
        month += 1
        if month > 12:
            month, year = 1, year + 1
        days_in_month = calendar.monthrange(year, month)[1]
    while total < 1:
        month -= 1
        if month < 1:
            month, year = 12, year - 1
        total += calendar.monthrange(year, month)[1]
    noon = time.mktime((year, month, total, 12, 0, 0, 0, 0, -1))
    return start_of_day(noon)


def day_key(ts: float) -> str:
    t = time.localtime(ts)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"


def month_key(ts: float) -> str:
    t = time.localtime(ts)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}"


def format_date(ts: float, fmt: str = "%a, %b %d") -> str:
    return time.strftime(fmt, time.localtime(ts))


def format_time(ts: float, fmt: str = "%H:%M") -> str:
    return time.strftime(fmt, time.localtime(ts))


def format_duration(seconds: float) -> str:
    """Coarse human duration, e.g. ``in 12 days`` / ``in 3 hours``."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "less than a minute"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} minute" + ("s" if minutes != 1 else "")
    hours, _ = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} hour" + ("s" if hours != 1 else "")
    days, _ = divmod(hours, 24)
    if days < 31:
        return f"{days} day" + ("s" if days != 1 else "")
    months, _ = divmod(days, 30)
    return f"{months} month" + ("s" if months != 1 else "")


def plural(count: float, word: str, suffix: str = "s") -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}{suffix}"
