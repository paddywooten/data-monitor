"""Traffic sampler.

Reads the kernel counters on a GLib timer inside the GTK main loop - the
reads are a single small ``/proc`` file so there is no reason to leave the
main thread.  Deltas are batched into minute buckets and flushed to SQLite.
"""

from __future__ import annotations

import time
from collections import deque

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from . import config as config_mod  # noqa: E402
from . import apptrack, netstat, quota, util  # noqa: E402

# Don't trust a rate computed over an implausibly long gap (laptop lid closed,
# system suspended, machine hibernated ...).  The bytes are still recorded,
# only the instantaneous rate is discarded.
def _sane_dt(dt: float, poll: float) -> bool:
    return 0.0 < dt <= max(10.0, poll * 5.0)


class Sampler:
    """Polls interface counters and maintains live rates + history."""

    # Bytes are flushed to disk on every sample: with WAL + synchronous=NORMAL
    # that is still several thousand transactions per second of headroom, and
    # it means the dashboard never shows stale zeroes.
    FLUSH_SECONDS = 0.0

    def __init__(
        self,
        storage,
        config: config_mod.Config,
        on_tick=None,
    ):
        self.storage = storage
        self.config = config
        self.on_tick = on_tick

        self.down_bps = 0.0
        self.up_bps = 0.0
        self.rates: dict[str, tuple[float, float]] = {}
        self.peak_down = 0.0
        self.peak_up = 0.0
        self.peak_day = ""

        self._prev: dict[str, tuple[int, int]] = {}
        self._last_monotonic = 0.0
        self._pending: dict[str, list[int]] = {}
        self._pending_apps: dict[str, list[int]] = {}
        self._pending_minute = 0
        self._last_flush = 0.0
        self._source_id = 0
        self._dirty_peak = False
        self._last_peak_save = 0.0

        # Per-program attribution (ss / iproute2); polled on the same tick.
        self.tracker = apptrack.AppTracker()
        self.tracker.reconfigure(self.config.track_apps)

        self.series: deque[tuple[float, float, float]] = deque(
            maxlen=self._series_len()
        )
        self._load_peaks()

    # -- tracked interfaces ----------------------------------------------
    @property
    def tracked(self) -> list[str]:
        if self.config.interfaces:
            return list(self.config.interfaces)
        return netstat.interface_names(
            include_loopback=not self.config.exclude_loopback
        )

    def _series_len(self) -> int:
        poll = max(0.2, float(self.config.poll_interval))
        return max(30, int(self.config.graph_window / poll) + 2)

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        if self._source_id:
            return
        self._prev = netstat.read_counters()
        self._last_monotonic = time.monotonic()
        self._last_flush = time.monotonic()
        self._pending_minute = self._current_minute()
        self._source_id = GLib.timeout_add(
            max(200, int(self.config.poll_interval * 1000)), self._tick
        )

    def stop(self) -> None:
        if self._source_id:
            GLib.source_remove(self._source_id)
            self._source_id = 0
        self.flush()

    def restart(self) -> None:
        """Re-arm the timer (after the poll interval changed)."""
        self.stop()
        self._resize_series()
        self.start()

    def _resize_series(self) -> None:
        wanted = self._series_len()
        if wanted == self.series.maxlen:
            return
        old = list(self.series)
        self.series = deque(old[-wanted:], maxlen=wanted)

    # -- the actual work --------------------------------------------------
    @staticmethod
    def _current_minute() -> int:
        return int(time.time() // 60) * 60

    def _tick(self) -> bool:
        now = time.monotonic()
        counters = netstat.read_counters()
        tracked = self.tracked
        dt = now - self._last_monotonic
        sane = self._prev and _sane_dt(dt, self.config.poll_interval)

        rate_down = 0.0
        rate_up = 0.0
        rates: dict[str, tuple[float, float]] = {}

        for name in tracked:
            cur = counters.get(name)
            old = self._prev.get(name)
            if cur is None:
                continue
            if old is None:
                # First time we see this adapter: establish a baseline only.
                continue
            drx = cur[0] - old[0]
            dtx = cur[1] - old[1]
            if drx < 0 or dtx < 0:
                # Counter reset (adapter reconnected / driver reloaded).
                drx = max(0, drx)
                dtx = max(0, dtx)
            pending = self._pending.setdefault(name, [0, 0])
            pending[0] += drx
            pending[1] += dtx
            if sane and dt > 0:
                r_down = drx * 8.0 / dt
                r_up = dtx * 8.0 / dt
                rates[name] = (r_down, r_up)
                rate_down += r_down
                rate_up += r_up

        self.rates = rates
        self.down_bps = rate_down
        self.up_bps = rate_up
        self.series.append((time.time(), rate_down, rate_up))
        self._update_peaks()

        # Per-app attribution: diff cumulative TCP socket counters.
        if self.tracker.enabled:
            for app, (rx, tx) in self.tracker.poll(
                count_loopback="lo" in tracked
            ).items():
                if rx > 0 or tx > 0:
                    bucket = self._pending_apps.setdefault(app, [0, 0])
                    bucket[0] += rx
                    bucket[1] += tx

        minute = self._current_minute()
        if minute != self._pending_minute or (now - self._last_flush) >= self.FLUSH_SECONDS:
            self.flush(new_minute=minute)

        self._prev = counters
        self._last_monotonic = now

        if self.on_tick:
            self.on_tick(self)
        return GLib.SOURCE_CONTINUE

    def flush(self, new_minute: int | None = None) -> None:
        minute = self._current_minute() if new_minute is None else new_minute
        if self._pending:
            for iface, (rx, tx) in list(self._pending.items()):
                if rx > 0 or tx > 0:
                    self.storage.add_usage(minute, iface, rx, tx)
            self._pending.clear()
        if self._pending_apps:
            for app, (rx, tx) in list(self._pending_apps.items()):
                if rx > 0 or tx > 0:
                    self.storage.add_app_usage(minute, app, rx, tx)
            self._pending_apps.clear()
        self._last_flush = time.monotonic()
        self._pending_minute = minute
        if self._dirty_peak:
            self._persist_peaks()

    # -- daily peaks ------------------------------------------------------
    def _load_peaks(self) -> None:
        self.peak_day = util.day_key(time.time())
        self.peak_down = self.storage.state_get_float(f"peak_down:{self.peak_day}", 0.0)
        self.peak_up = self.storage.state_get_float(f"peak_up:{self.peak_day}", 0.0)

    def _update_peaks(self) -> None:
        key = util.day_key(time.time())
        if key != self.peak_day:
            self.peak_day = key
            self.peak_down = 0.0
            self.peak_up = 0.0
            self._dirty_peak = True
        if self.down_bps > self.peak_down:
            self.peak_down = self.down_bps
            self._dirty_peak = True
        if self.up_bps > self.peak_up:
            self.peak_up = self.up_bps
            self._dirty_peak = True
        if self._dirty_peak and (time.monotonic() - self._last_peak_save) >= 15.0:
            self._persist_peaks()

    def _persist_peaks(self) -> None:
        self.storage.state_set_float(f"peak_down:{self.peak_day}", self.peak_down)
        self.storage.state_set_float(f"peak_up:{self.peak_day}", self.peak_up)
        self._dirty_peak = False
        self._last_peak_save = time.monotonic()

    # -- quota helpers used by the UI ------------------------------------
    @property
    def tracked_apps(self) -> set[str]:
        """Apps seen on live sockets right now (empty when tracking is off)."""
        return self.tracker.current_apps if self.tracker.enabled else set()

    def usage_today(self) -> tuple[int, int]:
        start, end = quota.day_bounds(time.time())
        return self.storage.totals(start, end, self.tracked)

    def usage_cycle(self) -> tuple[int, int]:
        start, _ = quota.cycle_bounds(time.time(), self.config.cycle_day)
        return self.storage.totals(start, int(time.time()) + 1, self.tracked)
