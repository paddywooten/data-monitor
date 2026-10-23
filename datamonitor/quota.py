"""Billing cycle / daily limit calculations (local time, DST safe)."""

from __future__ import annotations

import calendar
import time

from . import util


def cycle_bounds(now: float, cycle_day: int) -> tuple[int, int]:
    """Start (inclusive) and end (exclusive) of the billing cycle containing now."""
    cycle_day = min(28, max(1, int(cycle_day)))
    t = time.localtime(now)
    year, month = t.tm_year, t.tm_mon
    if t.tm_mday < cycle_day:
        month -= 1
        if month < 1:
            month, year = 12, year - 1

    start = _anchor(year, month, cycle_day)
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    end = _anchor(ny, nm, cycle_day)
    return start, end


def _anchor(year: int, month: int, day: int) -> int:
    day = min(day, calendar.monthrange(year, month)[1])
    noon = time.mktime((year, month, day, 12, 0, 0, 0, 0, -1))
    return util.start_of_day(noon)


def day_bounds(now: float) -> tuple[int, int]:
    start = util.start_of_day(now)
    return start, util.add_days(start, 1)


def cycle_index(now: float, cycle_day: int) -> str:
    """Stable identifier for the current cycle, e.g. ``2026-10``."""
    start, _ = cycle_bounds(now, cycle_day)
    return util.month_key(start + 3600)


def cycle_label(start: int, end: int) -> str:
    return f"{util.format_date(start, '%b %d')} – {util.format_date(util.add_days(end, -1), '%b %d')}"


def remaining_bytes(used: int, limit: int) -> int:
    return max(0, limit - used) if limit > 0 else 0


def usage_fraction(used: int, limit: int) -> float:
    if limit <= 0:
        return 0.0
    return min(9.99, used / limit)
