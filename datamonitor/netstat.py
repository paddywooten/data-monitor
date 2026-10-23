"""Reading interface byte counters without any privileges.

Everything comes from ``/proc/net/dev`` (cumulative counters maintained by
the kernel) plus a few ``/sys/class/net`` attributes for link details.
"""

from __future__ import annotations

import os

PROC_NET_DEV = "/proc/net/dev"
SYS_NET = "/sys/class/net"


def read_counters() -> dict[str, tuple[int, int]]:
    """Return ``{interface: (rx_bytes, tx_bytes)}`` for every interface."""
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


def interface_names(include_loopback: bool = False) -> list[str]:
    """Interfaces present right now, in kernel order."""
    names = list(read_counters())
    if not include_loopback:
        names = [n for n in names if n != "lo"]
    return names


def _sys_attr(iface: str, attr: str) -> str | None:
    path = os.path.join(SYS_NET, iface, attr)
    try:
        with open(path, "r", encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return None


def is_wireless(iface: str) -> bool:
    return os.path.isdir(os.path.join(SYS_NET, iface, "wireless"))


def link_state(iface: str) -> str:
    return (_sys_attr(iface, "operstate") or "unknown").lower()


def link_speed_mbps(iface: str) -> int | None:
    raw = _sys_attr(iface, "speed")
    if raw is None:
        return None
    try:
        speed = int(raw)
    except ValueError:
        return None
    return speed if speed > 0 else None


def describe(iface: str) -> dict:
    """Everything the interface tab wants to show about one adapter."""
    wireless = is_wireless(iface)
    if iface == "lo":
        kind = "Loopback"
    elif wireless:
        kind = "Wi-Fi"
    elif iface.startswith(("tun", "wg", "ppp")):
        kind = "VPN / tunnel"
    elif iface.startswith(("veth", "docker", "br", "virbr", "vw")):
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
