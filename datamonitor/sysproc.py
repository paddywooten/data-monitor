"""Cross-platform process primitives: suspend, resume, trees, identity.

The Linux implementations are the originals (``/proc`` + ``SIGSTOP`` /
``SIGCONT``), so existing behaviour is byte-identical.  Windows and macOS
go through psutil where a kernel view of the process tree is needed, plus
``NtSuspendProcess`` / ``NtResumeProcess`` on Windows, which has no
SIGSTOP equivalent.

Only ever called for our own user's processes; another user's process
fails with an OS error (access denied) that callers already ignore.
"""

from __future__ import annotations

import os
import signal
import sys

IS_LINUX = sys.platform.startswith("linux")

# Windows process right required by NtSuspendProcess / NtResumeProcess.
_PROCESS_SUSPEND_RESUME = 0x0800


def psutil_or_none():
    """psutil if installed, else None (the packaged builds always bundle it)."""
    try:
        import psutil

        return psutil
    except Exception:  # pragma: no cover - ImportError, broken wheel
        return None


def snapshot(pid: int) -> tuple[int, int] | None:
    """``(ppid, starttime)`` for a live pid, or ``None`` if it is gone.

    ``starttime`` makes pid reuse detectable, so we can never mistake a
    recycled pid for a process we paused earlier.  Linux reads it from
    ``/proc/<pid>/stat`` (clock ticks); elsewhere psutil's create time is
    used (epoch seconds) - both only ever compared against their own kind.
    """
    if IS_LINUX:
        return _proc_stat_linux(pid)
    ps = psutil_or_none()
    if ps is None:
        return None
    try:
        proc = ps.Process(pid)
        return proc.ppid() or 0, int(proc.create_time())
    except Exception:
        return None


def _proc_stat_linux(pid: int) -> tuple[int, int] | None:
    """``(ppid, starttime)`` from ``/proc/<pid>/stat``; ``None`` if gone.

    ``comm`` may contain spaces and parentheses, so only the fields after
    the *last* ``)`` are safe to split.  ``starttime`` (field 22) is the
    process' start in clock ticks.
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError:
        return None
    close = data.rfind(")")
    if close < 0:
        return None
    fields = data[close + 1:].split()
    if len(fields) < 20:
        return None
    try:
        return int(fields[1]), int(fields[19])
    except ValueError:
        return None


def same_user(pid: int) -> bool:
    """True when ``pid`` belongs to our user (never touch anyone else's)."""
    if IS_LINUX:
        try:
            return os.stat(f"/proc/{pid}").st_uid == os.getuid()
        except OSError:
            return False
    if os.name == "nt":
        # Windows enforces access rights on OpenProcess: another user's
        # process simply fails to suspend, which callers treat as "skip".
        return True
    ps = psutil_or_none()
    if ps is None:
        return False
    try:
        return ps.Process(pid).uids().real == os.getuid()
    except Exception:
        return False


def exe_name(pid: int) -> str | None:
    """Program name for a pid (stable across restarts), or ``None``."""
    if IS_LINUX:
        try:
            target = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None
        if target.endswith(" (deleted)"):
            target = target[: -len(" (deleted)")]
        name = os.path.basename(target)
        return name or None
    ps = psutil_or_none()
    if ps is None:
        return None
    try:
        return ps.Process(pid).name() or None
    except Exception:
        return None


def descendants(roots, exclude=()) -> set[int]:
    """``roots`` plus their descendants, never entering ``exclude`` subtrees.

    The root pids themselves are part of the result (callers filter
    protected / foreign pids separately for each stop attempt).
    """
    excluded = set(exclude)
    todo = [p for p in roots if p not in excluded]
    seen: set[int] = set()
    if IS_LINUX:
        # One pass over /proc: parent -> [children], then a BFS.
        children: dict[int, list[int]] = {}
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            stat = _proc_stat_linux(int(entry))
            if stat is None:
                continue
            children.setdefault(stat[0], []).append(int(entry))
        while todo:
            pid = todo.pop()
            if pid in seen or pid in excluded:
                continue
            seen.add(pid)
            todo.extend(children.get(pid, ()))
        return seen

    ps = psutil_or_none()
    if ps is None:
        return set(todo)

    def walk(proc) -> None:
        try:
            kids = proc.children()
        except Exception:
            return
        for kid in kids:
            if kid.pid in seen or kid.pid in excluded:
                continue
            seen.add(kid.pid)
            walk(kid)

    for root in todo:
        if root in seen:
            continue
        seen.add(root)
        try:
            walk(ps.Process(root))
        except Exception:
            continue
    return seen


def suspend(pid: int) -> bool:
    """Freeze a process; False when it is gone or not ours."""
    if os.name == "nt":
        return _nt_process_call(pid, "NtSuspendProcess")
    try:
        os.kill(pid, signal.SIGSTOP)
        return True
    except OSError:
        return False


def resume(pid: int) -> bool:
    """Thaw a process previously frozen by :func:`suspend`."""
    if os.name == "nt":
        return _nt_process_call(pid, "NtResumeProcess")
    try:
        os.kill(pid, signal.SIGCONT)
        return True
    except OSError:
        return False


def _nt_process_call(pid: int, symbol: str) -> bool:
    """Call ``NtSuspendProcess`` / ``NtResumeProcess`` on an open handle."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False  # gone, or another user's process (access denied)
    try:
        status = getattr(ctypes.windll.ntdll, symbol)(handle)
        return status == 0
    finally:
        kernel32.CloseHandle(handle)
