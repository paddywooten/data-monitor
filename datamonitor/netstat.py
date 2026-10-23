"""Reading interface byte counters without any privileges.

Linux reads ``/proc/net/dev`` (cumulative counters maintained by the
kernel) plus a few ``/sys/class/net`` attributes for link details - the
original, dependency-free path.  Windows and macOS have no procfs, so
those platforms use psutil, which asks the OS for the same counters.
"""

from __future__ import annotations

import os
import sys
import time

from . import sysproc

PROC_NET_DEV = "/proc/net/dev"
SYS_NET = "/sys/class/net"

# Loopback interface names across Linux / macOS / Windows.
LOOPBACK_NAMES = {"lo", "lo0", "Loopback Pseudo-Interface 1"}

# macOS: Wi-Fi / VPN names that Linux would discover in /sys.
_MAC_TUNNEL = ("utun", "ppp", "ipsec", "gif", "stf", "awdl", "llw")
_MAC_VIRTUAL = ("vmnet", "bridge", "vboxnet", "veth")
_WIN_TUNNEL = ("tailscale", "nordlynx", "wintun")
_WIN_VIRTUAL = ("virtual", "hyper-v", "docker", "vbox")


def _is_loopback_name(name: str) -> bool:
    return name in LOOPBACK_NAMES


def read_counters() -> dict[str, tuple[int, int]]:
    """Return ``{interface: (rx_bytes, tx_bytes)}`` for every interface."""
    if not sysproc.IS_LINUX:
        return _read_counters_psutil()
    counters: dict[str, tuple[int, int]] = {}
    try:
        with open(PROC_NET_DEV, "r", encoding="ascii") as fh:
            lines = fh.readlines()
    except OSError:
        return counters
    for line in lines[2:]:
        name, sep, rest = line.partition(":")
        if not sep:
            continue
        fields = rest.split()
        if len(fields) < 16:
            continue
        try:
            rx = int(fields[0])
            tx = int(fields[8])
        except ValueError:
            continue
        counters[name.strip()] = (rx, tx)
    return counters


def _read_counters_psutil() -> dict[str, tuple[int, int]]:
    ps = sysproc.psutil_or_none()
    if ps is None:
        return {}
    try:
        return {
            name: (io.bytes_recv, io.bytes_sent)
            for name, io in ps.net_io_counters(pernic=True).items()
        }
    except Exception:
        return {}


def interface_names(include_loopback: bool = False) -> list[str]:
    """Interfaces present right now, in kernel order."""
    names = list(read_counters())
    if not include_loopback:
        names = [n for n in names if not _is_loopback_name(n)]
    return names


# --------------------------------------------------------------------------
# link details
# --------------------------------------------------------------------------
def _if_stats() -> dict:
    """``psutil.net_if_stats()`` with a one-second cache (non-Linux only)."""
    now = time.monotonic()
    if now - _if_stats._stamp > 1.0:
        ps = sysproc.psutil_or_none()
        try:
            _if_stats._cache = ps.net_if_stats() if ps is not None else {}
        except Exception:
            _if_stats._cache = {}
        _if_stats._stamp = now
    return _if_stats._cache


_if_stats._cache: dict = {}
_if_stats._stamp = 0.0


def _sys_attr(iface: str, attr: str) -> str | None:
    path = os.path.join(SYS_NET, iface, attr)
    try:
        with open(path, "r", encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return None


def is_wireless(iface: str) -> bool:
    if sysproc.IS_LINUX:
        return os.path.isdir(os.path.join(SYS_NET, iface, "wireless"))
    return _is_wireless_other(iface)


def _is_wireless_other(iface: str) -> bool:
    lowered = iface.lower()
    if any(tag in lowered for tag in ("wi-fi", "wifi", "wireless", "wlan")):
        return True
    if sys.platform == "darwin":
        # macOS keeps the media type out of ifaddrs; ask networksetup once.
        return iface in _mac_wifi_devices()
    return False


def _mac_wifi_devices() -> set[str]:
    """``en0``-style device names of Wi-Fi hardware ports (cached forever)."""
    if not hasattr(_mac_wifi_devices, "_cache"):
        import subprocess

        cache: set[str] = set()
        try:
            out = subprocess.run(
                ["networksetup", "-listallhardwareports"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        device = None
        for line in out.splitlines():
            if line.startswith("Hardware Port:"):
                device = None
                if "wi-fi" in line.lower() or "airport" in line.lower():
                    device = "?"
            elif line.startswith("Device:") and device == "?":
                cache.add(line.split(":", 1)[1].strip())
        _mac_wifi_devices._cache = cache
    return _mac_wifi_devices._cache


def link_state(iface: str) -> str:
    if sysproc.IS_LINUX:
        return (_sys_attr(iface, "operstate") or "unknown").lower()
    stats = _if_stats().get(iface)
    if stats is None:
        return "unknown"
    return "up" if stats.isup else "down"


def link_speed_mbps(iface: str) -> int | None:
    if sysproc.IS_LINUX:
        raw = _sys_attr(iface, "speed")
        if raw is None:
            return None
        try:
            speed = int(raw)
        except ValueError:
            return None
        return speed if speed > 0 else None
    stats = _if_stats().get(iface)
    if stats is None:
        return None
    try:
        speed = int(stats.speed)
    except (TypeError, ValueError):
        return None
    return speed if speed > 0 else None


def describe(iface: str) -> dict:
    """Everything the interface tab wants to show about one adapter."""
    wireless = is_wireless(iface)
    if _is_loopback_name(iface):
        kind = "Loopback"
    elif wireless:
        kind = "Wi-Fi"
    elif iface.lower().startswith(("tun", "wg", "ppp", *_MAC_TUNNEL, *_WIN_TUNNEL)):
        kind = "VPN / tunnel"
    elif iface.lower().startswith(("veth", "docker", "br", "virbr", "vw", *_MAC_VIRTUAL, *_WIN_VIRTUAL)):
        kind = "Virtual"
    else:
        kind = "Ethernet"
    speed = link_speed_mbps(iface)
    return {
        "name": iface,
        "kind": kind,
        "wireless": wireless,
        "state": link_state(iface),
        "speed": speed,
        "up": link_state(iface) in ("up", "unknown"),
    }
