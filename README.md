# Data Monitor

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
- **Top apps** — attribute traffic to the programs actually sending it and see
  the biggest consumers on a dedicated **Apps** tab (TCP sockets via `ss`,
  still no root and no packet capture).
- **Restrictions** — give an app its own daily/cycle limit, and/or set an
  overall cap; when a limit is hit Data Monitor can *pause* the app (freeze it
  with `SIGSTOP` until the reset) instead of only notifying you.
- **Whitelists** — exempt critical apps (SSH, video calls, …) from every
  automatic pause: neither their own limits nor the overall cap ever freeze
  them.
- **History** — per-minute samples in SQLite, browsable as daily bars and a
  table (7 days / 30 days / this cycle / this year).
- **Per-interface breakdown** — Wi-Fi, Ethernet, VPN, tethering: see and choose
  what counts toward your limits.
- **Background monitoring** — close the window and it keeps recording; run
  `datamonitor` again to bring the dashboard back.
- **Starts at login** (optional), auto-dark/light following your desktop.

Built with GTK 4 + libadwaita, so it looks native next to your other apps.

---

## Requirements

| | |
|---|---|
| Python | 3.10+ (tested on 3.14) |
| GTK | 4.x + libadwaita 1.x |
| Python bindings | `python-gobject`, `pycairo` |
| iproute2 (`ss`) | per-app attribution — preinstalled on most distros |
| Desktop | any with XDG autostart + notifications |

Windows and macOS are supported through the packaged builds — see
[Building for Windows / macOS](#building-for-windows--macos).

On Arch / CachyOS:

```bash
sudo pacman -S python-gobject gtk4 libadwaita python-cairo iproute2
```

On Debian / Ubuntu:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-cairo iproute2
```

On Fedora:

```bash
sudo dnf install python3-gobject gtk4 libadwaita python3-cairo iproute
```

## Install

```bash
git clone https://github.com/paddywooten/data-monitor.git
cd data-monitor
./install.sh                 # app + launcher + icon + login autostart (background)
```

(`./install.sh` copies the app into `~/.local`, so the clone can be deleted
afterwards — or kept for updates: `cd data-monitor && git pull && ./install.sh`.)
Upgrading from an older install migrates your settings and history
automatically.)

Other options:

```bash
./install.sh --show-window   # autostart opens the dashboard instead of hiding it
./install.sh --no-autostart  # install only
./install.sh --systemd       # use a systemd --user service instead of autostart
./install.sh --help
```

Then either click **Data Monitor** in your application menu or run:

```bash
datamonitor
```

## Building for Windows / macOS

Two scripts at the repository root build self-contained apps **on the target
machine** — GTK cannot be cross-compiled, so build natively on each OS:

### Windows — `.exe` (+ optional installer)

1. Install [MSYS2](https://www.msys2.org), open the **MSYS2 MINGW64** shell,
   run once:

```bat
pacman -S --needed mingw-w64-x86_64-python mingw-w64-x86_64-python-gobject mingw-w64-x86_64-python-cairo mingw-w64-x86_64-gtk4 mingw-w64-x86_64-libadwaita mingw-w64-x86_64-python-psutil mingw-w64-x86_64-pyinstaller mingw-w64-x86_64-dbus
```

2. Build (from `cmd.exe`, or `cmd //c build-windows.bat` inside MSYS2):

```bat
build-windows.bat              &:: dist\DataMonitor\DataMonitor.exe (+ installer when Inno Setup 6 is present)
build-windows.bat install      &:: copy to %LOCALAPPDATA%\Data Monitor, start hidden at login
build-windows.bat uninstall    &:: remove app + autostart (data is kept)
```

[Inno Setup 6](https://jrsoftware.org/isinfo.php) is optional: without it you
get the portable folder, with it additionally
`dist\DataMonitor-Setup-<version>.exe` (per-user, no admin, optional
"start at login" task).

### macOS — `.app` + `.dmg`

1. Install [Homebrew](https://brew.sh), then run once:

```bash
brew install gtk4 libadwaita glib gdk-pixbuf cairo pango \
             pygobject pycairo python psutil pyinstaller dbus
```

2. Build:

```bash
./build-mac.sh              # dist/Data Monitor.app + dist/DataMonitor-<version>.dmg
./build-mac.sh install      # copy to ~/Applications, start hidden at login
./build-mac.sh uninstall    # remove app + login item (data is kept)
```

### What works where

| Feature | Linux | Windows / macOS |
|---|---|---|
| Live rates, quotas, warnings, history, peaks | ✓ | ✓ |
| Interfaces tab (kind, link state, speed) | ✓ | ✓ (best effort) |
| Apps tab: per-app usage + per-app limits | ✓ | — needs Linux `ss` counters |
| Pause apps when the **overall** cap is hit | ✓ | ✓ (pauses processes with TCP connections) |
| Whitelist / "resume until tomorrow" | Apps tab | config file only |
| Desktop notifications | ✓ | best effort (the in-app banner always works) |
| Background start (`--hidden`) + autostart | ✓ | ✓ (Run key / LaunchAgent) |

Things worth knowing about the packaged builds:

* **Single instance**: the frozen builds start a private `dbus-daemon`
  (bundled from MSYS2 / Homebrew) so launching a second time reopens the
  window instead of opening a second monitor — same behaviour as running
  `datamonitor` again on Linux. If no bus can be started, a lock file makes
  the second launch exit quietly instead.
* **Unsigned**: neither the `.exe` nor the `.dmg` is code-signed. Windows
  SmartScreen and macOS Gatekeeper warn on first start ("More info → Run
  anyway" / right-click → Open). Real distribution needs an Apple Developer
  ID (≈ $99/year) + notarization, or an Authenticode certificate.
* **Locations**: settings live in `%APPDATA%\datamonitor` (Windows) or
  `~/Library/Preferences/datamonitor` (macOS); history in
  `%LOCALAPPDATA%\datamonitor` respectively
  `~/Library/Application Support/datamonitor`.
* Interface naming (e.g. "Wi-Fi") and pause/resume use heuristics there;
  Linux stays the reference platform.

## Run straight from the source tree

```bash
python3 -m datamonitor
```

## Command line

```
datamonitor                 open the dashboard
datamonitor --hidden        start in the background (window hidden)
datamonitor --page apps     open on a tab: overview | history | apps | interfaces
datamonitor --settings      open Preferences on start
datamonitor --version
```

Launching `datamonitor` while it already runs simply brings the window back —
that is the documented way to reopen the background instance. (Installs up to
v1.1 used the `datawatch` command; it remains as an alias.)

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

**Apps** — who is using your data: a bar chart (scope picker: *Today / This
billing cycle / All time*) over a table of every program with its totals and a
status column. Anything not attributable to a TCP socket — UDP/QUIC, other
users, protocol overhead — shows up as the **Other** bar. The ⋮ menu on each
row:

- **Set or change limits…** — a daily and/or billing-cycle limit *for that app*.
  Preferences decides whether reaching it notifies you or pauses the app.
- **Whitelist — never pause** — the app is exempt from its own limits **and**
  from the overall "pause everything" cap. The dialog has the same switch.
- **Resume now** — unfreeze a paused app; it stays running until tomorrow.
  The banner's **Resume all** does that for everything at once.

When something is paused you get a banner (*N apps paused — limit reached* with
**Resume all**), a red *Paused — …* status on the row, and a desktop
notification. Data Monitor never leaves an app frozen: quitting it resumes
everything, and limits are re-checked every few seconds.

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
| Track per-app usage | Attribute traffic to programs (needs `ss`) |
| When my overall limit is hit | Notify me / **Pause the app(s)** |
| When an app's own limit is hit | Notify me / **Pause the app(s)** |
| Desktop notifications | Toggle the quota notifications |
| Keep running when closed | Close-to-background behaviour |
| Appearance | Follow system / light / dark |

Volumes are shown in **decimal** units (`1 GB = 1 000 000 000 bytes`) because
that is how ISPs quote quotas; speeds use bits (`Mbps`).

---

## How it works

```
 /proc/net/dev ──(every 2 s)──▶ Sampler ──(per-minute buckets)──▶ SQLite
   ss -Htinp ────(same tick)──▶ per-app deltas ──┘
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

### Per-app attribution & restrictions

- Every tick `ss -Htinp` lists TCP sockets with their cumulative byte counters
  and owning process; diffing per socket yields per-program byte deltas.
  Same principle as the interface counters: no packet capture, no privileges.
  *(Linux only: Windows and macOS do not expose per-socket byte counters to
  user space, so the Apps tab and per-app limits need Linux; the overall cap
  pause still works there — see
  [What works where](#what-works-where).)*
- **TCP only.** UDP/QUIC (much of video calling, DNS, games), traffic from
  other users and protocol overhead land in **Other**. Loopback is skipped
  unless you track `lo`.
- Pausing uses plain `SIGSTOP`/`SIGCONT` on the app's **own process tree**
  (`NtSuspendProcess` on Windows): your user only — never other users'
  processes, never Data Monitor itself or its launcher tree. Each stopped pid
  is recorded with its process start time, so a recycled pid can never be
  resumed by mistake.
- The enforcer re-checks every 5 s and is idempotent: whitelist an app and it
  resumes within seconds; hitting *Resume now* holds until the next day;
  turning tracking off, or quitting Data Monitor, resumes everything.

### Files

| Path | Contents |
|---|---|
| `~/.config/datamonitor/config.json` | settings — limits, actions, per-app limits, whitelist |
| `~/.local/share/datamonitor/history.sqlite3` | usage history |
| `~/.local/share/datamonitor/datamonitor/` | installed copy of the app |
| `~/.local/bin/datamonitor` | launcher (`datawatch` kept as alias) |
| `~/.local/share/applications/io.datamonitor.App.desktop` | menu entry |
| `~/.config/autostart/datamonitor.desktop` | login autostart |

Set `DATAMONITOR_CONFIG_HOME` / `DATAMONITOR_DATA_HOME` to point the app at
different directories (used for testing or a portable install). The older
`DATAWATCH_CONFIG_HOME` / `DATAWATCH_DATA_HOME` names still work.
The Windows / macOS builds use `%APPDATA%\datamonitor`,
`%LOCALAPPDATA%\datamonitor`, `~/Library/Preferences/datamonitor` and
`~/Library/Application Support/datamonitor` instead (see
[Building for Windows / macOS](#building-for-windows--macos)).

---

## Troubleshooting

**Totals stay at 0** — check the Interfaces tab: your adapter must be switched
on (*Counted*). Loopback traffic never counts; a VPN tunnel counts only if it
appears as its own interface.

**Usage looks too high / too low** — confirm which interfaces are counted, and
that the billing-cycle start day matches your plan.

**The Apps tab is empty** — turn on *Track per-app usage* in Preferences and
make sure `ss` is installed (`iproute2`). If much of your usage sits in
*Other*, that is UDP/QUIC or another user's traffic: attribution is TCP-only
by design.

**An app stayed paused** — shouldn't happen (Data Monitor resumes everything on
quit), but you can always SIGCONT it yourself or use **Resume all** in the
Apps tab after starting `datamonitor`.

**No notifications** — the desktop needs a notification daemon (KDE and GNOME
have one). You can turn them off entirely in Preferences; the banner always
works.

**The window is gone but it is "running"** — that is background mode. Run
`datamonitor` again, or click the *Open Data Monitor* button on the
notification. Stop it for good from the menu (**⋮ → Quit**, `Ctrl+Q`).

**Wrong window class / icon** — run `./install.sh` again after moving the
project; the generated launcher and desktop entry reference absolute paths.

## Uninstall

```bash
./uninstall.sh           # keep history and settings
./uninstall.sh --purge   # delete them too
```

## License

MIT — see [LICENSE](LICENSE).
