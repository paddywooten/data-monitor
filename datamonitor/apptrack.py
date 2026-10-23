"""Per-application traffic attribution without root.

Linux only: ``ss`` (iproute2) asks the kernel for every TCP socket
together with its cumulative ``bytes_received`` / ``bytes_acked``
counters and the owning process.  Diffing those counters between polls
yields byte deltas per program:

* TCP only - UDP/QUIC traffic and other users' sockets stay in the
  "unattributed" remainder shown on the Apps page;
* no privileges needed: our own user's sockets map to processes through
  ``/proc``;
* a full ``ss`` scan costs ~20 ms, so it fits the existing GLib tick.

Windows and macOS have no per-socket byte counters a user can read, so
there the tracker runs in a reduced *pids-only* mode: psutil lists the
process behind every TCP connection, which is enough for the enforcer to
pause apps when the overall cap is hit, but it cannot split bytes per
program (``has_bytes`` is False and the Apps tab says so).
"""

from __future__ import annotations

import re
import shutil
import subprocess

from . import sysproc

_USERS_RE = re.compile(r'users:\(\("([^"]+)",\s*pid=(\d+),\s*fd=(\d+)\)')
_RX_RE = re.compile(r"\bbytes_received:(\d+)")
_TX_RE = re.compile(r"\bbytes_acked:(\d+)")


def _exe_name(pid: int) -> str | None:
    """Program name for a pid (stable across restarts)."""
    return sysproc.exe_name(pid)


def _is_loopback(local: str) -> bool:
    host = local.rsplit(":", 1)[0]
    return host.startswith("127.") or host in ("[::1]", "::1")


def _blocks(text: str):
    """Split ``ss`` output into per-socket blocks (header + info lines)."""
    current: list[str] = []
    for line in text.splitlines():
        if line and not line[0].isspace():
            if current:
                yield current
            current = [line]
        elif current:
            current.append(line)
    if current:
        yield current


class AppTracker:
    """Turns cumulative per-socket counters into per-app byte deltas."""

    def __init__(self) -> None:
        if sysproc.IS_LINUX:
            self.has_bytes = shutil.which("ss") is not None
            self.available = self.has_bytes
        else:
            # pids-only: enough for the enforcer, not for byte attribution.
            self.has_bytes = False
            self.available = sysproc.psutil_or_none() is not None
        self.enabled = False  # set from config via reconfigure()
        # (pid, fd) -> (bytes_received, bytes_acked, starttime)
        self._sockets: dict[tuple[int, int], tuple[int, int, int]] = {}
        self._pids: dict[str, list[int]] = {}

    # -- configuration ----------------------------------------------------
    def reconfigure(self, enabled: bool) -> None:
        """Apply the ``track_apps`` setting; baselines restart from zero."""
        if sysproc.IS_LINUX:
            self.enabled = bool(enabled and self.available)
        else:
            # No byte attribution to switch off; the enforcer still needs
            # the pid map, so pids-only tracking is always on when possible.
            self.enabled = self.available
        if not self.enabled:
            self.reset()

    def reset(self) -> None:
        self._sockets.clear()
        self._pids.clear()

    # -- introspection for the enforcer / UI ------------------------------
    @property
    def current_apps(self) -> set[str]:
        return set(self._pids)

    def pids_for(self, app: str) -> list[int]:
        return list(self._pids.get(app, ()))

    # -- the poll ---------------------------------------------------------
    def poll(self, count_loopback: bool) -> dict[str, list[int]]:
        """Read all TCP sockets; return ``{app: [rx_delta, tx_delta]}``."""
        if not self.enabled:
            return {}
        if not sysproc.IS_LINUX:
            return self._poll_pids_only(count_loopback)
        try:
            out = subprocess.run(
                ["ss", "-Htinp"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
        except (OSError, subprocess.SubprocessError):
            return {}

        deltas: dict[str, list[int]] = {}
        seen: dict[tuple[int, int], tuple[int, int, int]] = {}
        pids: dict[str, list[int]] = {}

        for block in _blocks(out.stdout):
            text = " ".join(block)
            users = _USERS_RE.search(text)
            if not users:
                continue  # no owner we can see (other user / kernel socket)
            comm, pid, fd = users.group(1), int(users.group(2)), int(users.group(3))
            fields = block[0].split()
            if len(fields) < 5:
                continue
            if not count_loopback and _is_loopback(fields[3]):
                continue
            rx, tx = _RX_RE.search(text), _TX_RE.search(text)
            if not rx or not tx:
                continue
            stat = sysproc.snapshot(pid)
            if stat is None:
                continue
            starttime = stat[1]

            key = (pid, fd)
            base_rx, base_tx = int(rx.group(1)), int(tx.group(1))
            prev = self._sockets.get(key)
            drx = dtx = 0
            if prev is not None and prev[2] == starttime:
                # Negative deltas (fd reused, counter reset) become baselines.
                drx = max(0, base_rx - prev[0])
                dtx = max(0, base_tx - prev[1])
            seen[key] = (base_rx, base_tx, starttime)

            name = _exe_name(pid) or comm or f"pid:{pid}"
            if drx or dtx:
                bucket = deltas.setdefault(name, [0, 0])
                bucket[0] += drx
                bucket[1] += dtx
            bucket_pids = pids.setdefault(name, [])
            if pid not in bucket_pids:
                bucket_pids.append(pid)

        # Closed sockets drop out here; their final bytes land in "Other".
        self._sockets = seen
        self._pids = pids
        return deltas

    # -- pids-only mode (Windows / macOS) ---------------------------------
    def _poll_pids_only(self, count_loopback: bool) -> dict[str, list[int]]:
        """Refresh ``{app: [pids]}`` from live TCP connections; no bytes."""
        ps = sysproc.psutil_or_none()
        if ps is None:
            return {}
        try:
            connections = ps.net_connections(kind="tcp")
        except Exception:
            return {}
        pids: dict[str, list[int]] = {}
        for conn in connections:
            if not conn.pid:
                continue  # system socket or another user's process
            if not count_loopback and _conn_is_loopback(conn):
                continue
            name = _exe_name(conn.pid) or f"pid:{conn.pid}"
            bucket = pids.setdefault(name, [])
            if conn.pid not in bucket:
                bucket.append(conn.pid)
        self._pids = pids
        return {}


def _conn_is_loopback(conn) -> bool:
    """True when the local address of a psutil connection is loopback."""
    try:
        host = conn.laddr.ip
    except (AttributeError, IndexError):
        return False
    return host.startswith("127.") or host == "::1"
