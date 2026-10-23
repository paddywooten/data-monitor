# Datawatch

A small internet **data usage monitor** for your laptop.

It watches the traffic on your network interfaces, shows live speeds, keeps
weeks of history and warns you before you burn through a monthly quota.

- **No root, no packet capture** — it reads the kernel's own per-interface byte
  counters from `/proc/net/dev`, so nothing is ever sniffed and nothing needs
  `sudo`.
- **Live dashboard** — current download/upload rate with a rolling speed graph.
- **Data limits** — set a billing-cycle allowance and/or a daily allowance, with
  a warning threshold (80 % by default). You get an in-app banner *and* a
  desktop notification when you get close or go over.
- **History** — per-minute samples in SQLite, browsable as daily bars and a
  table (7 days / 30 days / this cycle / this year).
- **Per-interface breakdown** — Wi-Fi, Ethernet, VPN, tethering: see and choose
  what counts toward your limits.
- **Background monitoring** — close the window and it keeps recording; run
  `datawatch` again to bring the dashboard back.
- **Starts at login** (optional), auto-dark/light following your desktop.

Built with GTK 4 + libadwaita, so it looks native next to your other apps.

---

## Requirements

| | |
|---|---|
| Python | 3.10+ (tested on 3.14) |
| GTK | 4.x + libadwaita 1.x |
| Python bindings | `python-gobject`, `pycairo` |
| Desktop | any with XDG autostart + notifications |

On Arch / CachyOS:

```bash
sudo pacman -S python-gobject gtk4 libadwaita python-cairo
```

On Debian / Ubuntu:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-cairo
```

On Fedora:

```bash
sudo dnf install python3-gobject gtk4 libadwaita python3-cairo
```

## Install

```bash
git clone https://github.com/paddywooten/data-monitor.git
cd data-monitor
./install.sh                 # app + launcher + icon + login autostart (background)
```

(`./install.sh` copies the app into `~/.local`, so the clone can be deleted
afterwards — or kept for updates: `cd data-monitor && git pull && ./install.sh`.)

Other options:

```bash
./install.sh --show-window   # autostart opens the dashboard instead of hiding it
./install.sh --no-autostart  # install only
./install.sh --systemd       # use a systemd --user service instead of autostart
./install.sh --help
```

Then either click **Datawatch** in your application menu or run:

```bash
datawatch
```

## Run straight from the source tree

```bash
python3 -m datawatch
```

## Command line

```
datawatch                 open the dashboard
datawatch --hidden        start in the background (window hidden)
datawatch --page history  open on a tab: overview | history | interfaces
datawatch --settings      open Preferences on start
datawatch --version
```

Launching `datawatch` while it already runs simply brings the window back —
that is the documented way to reopen the background instance.

---

## Using it

**Overview**

- *Download now / Upload now* — instantaneous rates (peak of the day underneath).
- *Today / This cycle / Remaining / All time* — volume totals against your limits.
- The banner across the top shows cycle progress and turns amber then red as you
  approach a limit. **Adjust** jumps straight to Preferences.
- The graph shows the last `graph_window` seconds (default 3 minutes).

**History** — pick a range, hover a bar for the exact figure, and read the table
below. Bars turn amber at your warning threshold and red past the daily limit.

**Interfaces** — each adapter with its kind, link state, current rate, and
today / cycle / all-time totals. The switch decides whether it counts toward
your limits and totals. Loops back in automatically (VPN up? docked?) when you
leave it on *Automatic*.

**Preferences** (`Ctrl+,`)

| Setting | Meaning |
|---|---|
| Billing cycle limit | Allowance per cycle, in GB. `0` = no limit |
| Daily limit | Allowance per calendar day, in GB. `0` = no limit |
| Warn me at | Percentage of a limit that triggers the warning |
| Billing cycle starts on | Day of month the quota resets (1–28) |
| Tracked interfaces | Which adapters are counted; the ↻ button rescans |
| Sampling interval | Seconds between counter reads (1–60) |
| Graph window | Seconds of live history (30–3600) |
| History retention | Days of samples kept (default 730) |
| Desktop notifications | Toggle the quota notifications |
| Keep running when closed | Close-to-background behaviour |
| Appearance | Follow system / light / dark |

Volumes are shown in **decimal** units (`1 GB = 1 000 000 000 bytes`) because
that is how ISPs quote quotas; speeds use bits (`Mbps`).

---

## How it works

```
 /proc/net/dev ──(every 2 s)──▶ Sampler ──(per-minute buckets)──▶ SQLite
                                       └──▶ live rates ──▶ graph / cards
                                                             └──▶ quota checks ──▶ banner + notification
```

- Counters are cumulative, so the app never needs privileges and never sees
  packet contents — only interface totals. Counter resets (Wi-Fi reconnect,
  driver reload) are detected and handled.
- Samples are aggregated into `(minute, interface)` rows; at the default
  settings that is about **700 KB of database per year** per interface.
- Implausible rates (laptop suspended, lid closed) are ignored for the live
  graph while the bytes are still recorded — so a resume after sleep never
  produces a spike.
- Retention prunes old rows on startup; lifetime totals are kept separately so
  "All time" never shrinks when old data is pruned.

### Files

| Path | Contents |
|---|---|
| `~/.config/datawatch/config.json` | settings |
| `~/.local/share/datawatch/history.sqlite3` | usage history |
| `~/.local/share/datawatch/datawatch/` | installed copy of the app |
| `~/.local/bin/datawatch` | launcher |
| `~/.local/share/applications/io.datawatch.App.desktop` | menu entry |
| `~/.config/autostart/datawatch.desktop` | login autostart |

Set `DATAWATCH_CONFIG_HOME` / `DATAWATCH_DATA_HOME` to point the app at
different directories (used for testing or a portable install).

---

## Troubleshooting

**Totals stay at 0** — check the Interfaces tab: your adapter must be switched
on (*Counted*). Loopback traffic never counts; a VPN tunnel counts only if it
appears as its own interface.

**Usage looks too high / too low** — confirm which interfaces are counted, and
that the billing-cycle start day matches your plan.

**No notifications** — the desktop needs a notification daemon (KDE and GNOME
have one). You can turn them off entirely in Preferences; the banner always
works.

**The window is gone but it is "running"** — that is background mode. Run
`datawatch` again, or click the *Open Datawatch* button on the notification.
Stop it for good from the menu (**⋮ → Quit**, `Ctrl+Q`).

**Wrong window class / icon** — run `./install.sh` again after moving the
project; the generated launcher and desktop entry reference absolute paths.

## Uninstall

```bash
./uninstall.sh           # keep history and settings
./uninstall.sh --purge   # delete them too
```

## License

MIT — see [LICENSE](LICENSE).
