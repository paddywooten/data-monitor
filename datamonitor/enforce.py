"""Limit enforcement: pause / resume application process trees.

Everything here works unprivileged - suspending our own user's processes
needs no root (SIGSTOP / SIGCONT on POSIX, ``NtSuspendProcess`` /
``NtResumeProcess`` on Windows, see ``sysproc``).  ``evaluate()`` is a
reconciler that runs every few seconds and brings reality in line with
the configured rules:

* app over its own limit  -> pause it (unless whitelisted)
* overall cap exceeded    -> pause every app with traffic (minus whitelist)
* no rule applies anymore -> resume what we paused

The stopped pid sets are recorded in SQLite together with each pid's
start time, so pid reuse can never resume a stranger - and a restarted
Data Monitor can resume (or re-assert) what the previous run paused.
Whitelisted apps are never touched.

Per-app limits need byte attribution (Linux, ``ss``).  The overall cap
pause also works on Windows and macOS, where the tracker runs in
pids-only mode and pauses the processes holding TCP connections.
"""

from __future__ import annotations

import json
import os
import time

from . import quota, sysproc, util


class Enforcer:
    """Reconciles "what should be paused" with "what is paused"."""

    def __init__(self, config, storage, notify=None):
        self.config = config
        self.storage = storage
        # notify(nid, title, body, urgent) -> None, wired up by the app.
        self._notify = notify
        self._protected: set[int] = set()
        self._refresh_protected()

    # -- process plumbing -------------------------------------------------
    def _refresh_protected(self) -> None:
        """Our own pid, every ancestor, and pid 1: never signal those.

        This also covers "launched from a terminal / the session manager",
        which keeps the launcher tree (and this agent's harness) safe.
        """
        protected = {os.getpid(), 1}
        pid = os.getppid()
        for _ in range(16):
            if pid <= 1 or pid in protected:
                break
            protected.add(pid)
            stat = sysproc.snapshot(pid)
            if stat is None:
                break
            pid = stat[0]
        self._protected = protected

    def _stop_tree(self, roots) -> dict[int, int]:
        """Freeze ``roots`` and their descendants; return {pid: starttime}."""
        self._refresh_protected()
        seen = sysproc.descendants(roots, self._protected)

        stopped: dict[int, int] = {}
        for pid in seen:
            if not sysproc.same_user(pid):
                continue  # never touch another user's processes
            stat = sysproc.snapshot(pid)
            if stat is None:
                continue
            if not sysproc.suspend(pid):
                continue
            stopped[pid] = stat[1]
        return stopped

    @staticmethod
    def _continue(pids: dict[int, int]) -> None:
        """Thaw recorded pids whose starttime still matches."""
        for pid, starttime in pids.items():
            stat = sysproc.snapshot(pid)
            if stat is None or stat[1] != starttime:
                continue  # gone or recycled - never signal a stranger
            if not sysproc.same_user(pid):
                continue
            sysproc.resume(pid)

    # -- public API -------------------------------------------------------
    def paused(self) -> dict[str, dict]:
        """``{app: {"pids": {pid: starttime}, "reason": str, "at": int}}``"""
        result = {}
        for app, pids, reason, at in self.storage.list_paused():
            try:
                decoded = {int(p): int(st) for p, st in json.loads(pids).items()}
            except (ValueError, TypeError):
                decoded = {}
            if decoded:
                result[app] = {"pids": decoded, "reason": reason, "at": at}
        return result

    def evaluate(self, sampler) -> None:
        """Reconcile enforcement state (called every few seconds)."""
        cfg = self.config
        storage = self.storage
        paused = self.paused()

        tracker = getattr(sampler, "tracker", None)
        if (
            tracker is None
            or not tracker.available
            or (sysproc.IS_LINUX and not cfg.track_apps)
        ):
            # No attribution -> no enforcement; never leave apps frozen.
            # Off-Linux the pid map is always on: track_apps only governs
            # byte attribution, which those platforms cannot do anyway.
            for app, rec in paused.items():
                self._resume(app, rec)
            return

        now = time.time()
        today = util.day_key(now)
        day_start, _ = quota.day_bounds(now)
        cycle_start, _ = quota.cycle_bounds(now, cfg.cycle_day)
        horizon = int(now) + 1

        day_usage = {
            app: rx + tx
            for app, rx, tx in storage.app_totals_range(day_start, horizon)
        }
        cycle_usage = {
            app: rx + tx
            for app, rx, tx in storage.app_totals_range(cycle_start, horizon)
        }

        whitelist = set(cfg.app_whitelist)
        want: dict[str, str] = {}

        # -- per-app rules ------------------------------------------------
        if cfg.app_action == "pause":
            for app, limits in cfg.app_limits.items():
                if app in whitelist:
                    continue
                daily = int(float(limits.get("daily_mb", 0)) * 1_000_000)
                cyc = int(float(limits.get("cycle_mb", 0)) * 1_000_000)
                reason = None
                if daily > 0 and day_usage.get(app, 0) >= daily:
                    reason = "daily limit"
                elif cyc > 0 and cycle_usage.get(app, 0) >= cyc:
                    reason = "billing-cycle limit"
                if reason:
                    want[app] = reason

        # -- overall rule -------------------------------------------------
        if cfg.overall_action == "pause":
            cap = self._overall_cap_reason(sampler, day_start, horizon, cycle_start)
            if cap:
                for app in set(day_usage) | set(tracker.current_apps):
                    if app in whitelist or app in want:
                        continue
                    want[app] = f"overall {cap}"

        # -- reconcile ----------------------------------------------------
        for app, rec in list(paused.items()):
            suppressed = storage.state_get(f"resume:{app}") == today
            if app in want and not suppressed:
                self._ensure(app, rec, tracker)
            else:
                self._resume(app, rec)

        new_overall: list[str] = []
        for app, reason in want.items():
            if app in paused:
                continue  # handled above
            if storage.state_get(f"resume:{app}") == today:
                continue  # the user chose "resume until tomorrow"
            if self._pause(app, reason, sampler) and reason.startswith("overall"):
                new_overall.append(app)

        if new_overall:
            self._notify_overall(new_overall)

    def resume_now(self, app: str) -> None:
        """Manual resume: holds until tomorrow (or until limits change)."""
        rec = self.paused().get(app)
        if rec:
            self._resume(app, rec)
        self.storage.state_set(f"resume:{app}", util.day_key(time.time()))

    def resume_all(self, manual: bool = False) -> None:
        for app, rec in self.paused().items():
            self._resume(app, rec)
            if manual:
                self.storage.state_set(f"resume:{app}", util.day_key(time.time()))

    def shutdown(self) -> None:
        """Never leave apps frozen when Data Monitor exits."""
        for app, rec in self.paused().items():
            self._resume(app, rec)

    # -- rules ------------------------------------------------------------
    def _overall_cap_reason(
        self, sampler, day_start: int, horizon: int, cycle_start: int
    ) -> str | None:
        cfg = self.config
        cycle_limit = cfg.cycle_limit_bytes()
        if cycle_limit > 0:
            rx, tx = self.storage.totals(cycle_start, horizon, sampler.tracked)
            if rx + tx >= cycle_limit:
                return "billing-cycle cap"
        day_limit = cfg.day_limit_bytes()
        if day_limit > 0:
            rx, tx = self.storage.totals(day_start, horizon, sampler.tracked)
            if rx + tx >= day_limit:
                return "daily cap"
        return None

    # -- actions ----------------------------------------------------------
    def _pause(self, app: str, reason: str, sampler) -> bool:
        tracker = getattr(sampler, "tracker", None)
        if tracker is None:
            return False
        roots = [p for p in tracker.pids_for(app) if p not in self._protected]
        if not roots:
            return False  # protected / not running right now - retry later
        stopped = self._stop_tree(roots)
        if not stopped:
            return False
        now = time.time()
        self.storage.add_paused(app, json.dumps(stopped), reason, int(now))

        if not reason.startswith("overall"):
            # Individual pauses notify per app; overall pauses are grouped.
            self._notify_once(
                nid=f"paused-{app}",
                title=f"{app} paused",
                body=(
                    f"Reached its {reason}. It resumes at the next reset, "
                    "or from the Apps tab."
                ),
            )
        return True

    def _ensure(self, app: str, rec: dict, tracker) -> None:
        """Keep an already-recorded pause actually stopped."""
        still: dict[int, int] = {}
        for pid, starttime in rec["pids"].items():
            stat = sysproc.snapshot(pid)
            if stat is not None and stat[1] == starttime:
                if pid in self._protected:
                    continue
                if sysproc.suspend(pid):  # idempotent
                    still[pid] = starttime
        if still:
            if still != rec["pids"]:
                self.storage.add_paused(
                    app, json.dumps(still), rec["reason"], rec["at"]
                )
            return
        # All recorded pids are gone (app restarted?) - re-assert on new ones.
        fresh = self._stop_tree(tracker.pids_for(app)) if tracker else {}
        if fresh:
            self.storage.add_paused(app, json.dumps(fresh), rec["reason"], rec["at"])

    def _resume(self, app: str, rec: dict) -> None:
        self._continue(rec["pids"])
        self.storage.remove_paused(app)

    # -- notifications ----------------------------------------------------
    def _notify_once(self, nid: str, title: str, body: str) -> None:
        if not self.config.notify or self._notify is None:
            return
        marker = f"notified:{nid}:{util.day_key(time.time())}"
        if self.storage.state_get(marker) is not None:
            return
        self._notify(nid, title, body, True)
        self.storage.state_set(marker, util.day_key(time.time()))

    def _notify_overall(self, apps: list[str]) -> None:
        names = sorted(apps)
        shown = ", ".join(names[:3])
        if len(names) > 3:
            shown += f" +{len(names) - 3} more"
        self._notify_once(
            nid="paused-all",
            title="Apps paused — data limit reached",
            body=f"Paused: {shown}. They resume at the reset, or from the Apps tab.",
        )
