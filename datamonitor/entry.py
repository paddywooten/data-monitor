"""Entry point for the frozen builds (PyInstaller .exe / .app).

On Linux we are always started as ``python -m datamonitor`` and nothing
in here runs.  The packaged Windows / macOS builds land here instead,
because they need two things a source checkout never does:

* a D-Bus session bus - GApplication's single-instance hand-off talks to
  one.  Neither Windows nor macOS provides a bus by default, so if the
  environment does not already have one we start a private
  ``dbus-daemon`` (bundled next to the executable) and share its address
  through a small state file.  A second launch then reuses the same bus,
  and the running instance presents its window - exactly like running
  ``datamonitor`` again does on Linux.
* a lock-file fallback: when no bus could be started, a second launch
  exits quietly instead of opening a second monitor (two samplers would
  double-count into the same database).
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import tempfile

from . import APP_NAME

_DAEMON: subprocess.Popen | None = None
_LOCK = None  # held file object for the lock-file fallback


def _runtime_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    else:
        base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    path = os.path.join(base, "datamonitor")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = tempfile.gettempdir()
    return path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(
            handle, ctypes.byref(code)
        )
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == still_active
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False
    return True


def _read_bus_file(path: str) -> tuple[int, str] | None:
    """``(pid, address)`` recorded by a still-running instance, if any."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            pid_text, address = fh.read().split(maxsplit=1)
        pid = int(pid_text)
        address = address.strip()
    except (OSError, ValueError):
        return None
    if address.startswith("unix:") and _pid_alive(pid):
        return pid, address
    return None


def _write_bus_file(path: str, address: str) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {address}\n")
        os.replace(tmp, path)
    except OSError:
        pass


def _find_dbus_daemon() -> str | None:
    """The bundled (or PATH) dbus-daemon, if there is one."""
    name = "dbus-daemon.exe" if os.name == "nt" else "dbus-daemon"
    candidates = [name]
    frozen_dir = getattr(sys, "_MEIPASS", None)
    exe_dir = os.path.dirname(sys.executable)
    for base in (frozen_dir, exe_dir):
        if base:
            candidates.insert(0, os.path.join(base, name))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    import shutil

    return shutil.which(name)


def _ensure_session_bus() -> None:
    """Give a frozen build a session bus, shared across all its launches."""
    global _DAEMON
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return
    state = os.path.join(_runtime_dir(), "session-bus")
    existing = _read_bus_file(state)
    if existing:
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = existing[1]
        return
    exe = _find_dbus_daemon()
    if exe is None:
        return
    try:
        daemon = subprocess.Popen(
            [exe, "--session", "--nofork", "--print-address=1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return
    address = ""
    try:
        assert daemon.stdout is not None
        address = daemon.stdout.readline().strip()
    except OSError:
        address = ""
    if not address.startswith("unix:"):
        # Did not come up; do not leave a half-started daemon behind.
        try:
            daemon.terminate()
        except OSError:
            pass
        return
    _DAEMON = daemon
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
    _write_bus_file(state, address)
    atexit.register(_cleanup_bus, state)


def _cleanup_bus(state: str) -> None:
    try:
        os.remove(state)
    except OSError:
        pass
    if _DAEMON is not None and _DAEMON.poll() is None:
        try:
            _DAEMON.terminate()
            _DAEMON.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass


def _claim_instance_lock() -> bool:
    """Hold the single-instance lock; False when someone else already does."""
    global _LOCK
    path = os.path.join(_runtime_dir(), "instance.lock")
    try:
        fh = open(path, "a+")
    except OSError:
        return True  # cannot lock - behave as before and just run
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
    except OSError:
        pass
    _LOCK = fh  # keep the lock for the lifetime of the process
    return True


def run() -> int:
    """Bootstrap a frozen build, then hand over to the normal main()."""
    if not sys.platform.startswith("linux") and getattr(sys, "frozen", False):
        _ensure_session_bus()
        if (
            not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            and not _claim_instance_lock()
        ):
            print(f"{APP_NAME} is already running.", file=sys.stderr)
            return 0
    from .__main__ import main

    return main()


if __name__ == "__main__":
    raise SystemExit(run())
