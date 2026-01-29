<div align="center">

# Lemux

Soft app-to-interface routing for Linux

</div>

---

## Overview

Lemux routes specific applications through a chosen network interface using policy routing by user (uidrange) plus nftables packet marks (fwmark). It launches apps under dedicated system users, so any app can be routed **without namespaces**. The same dedicated user can be reused across multiple apps.

Tested on Debian and Ubuntu. Compatible with Portmaster.

## Features

- Dedicated user per app (or reuse an existing Lemux user for another app)
- Works for any application (uidrange + fwmark via nftables)
- Supports Chromium-based browsers (profile toggle available)
- GUI and CLI workflows
- Desktop entry creation and management
- App state stored in `~/.config/.lemux`

## Prerequisites

System packages:

```bash
sudo apt update
sudo apt install -y python3 python3-tk iproute2 nftables acl
```

Python deps:

```bash
python3 -m pip install -r requirements.txt
```

## Quick start (GUI)

```bash
python3 gui/app.py
```

The GUI will elevate via `pkexec` when needed.

## GUI usage

1. Select an interface.
2. Enter app command (binary + args) and add it to the queue.
3. Click **Assign**.
4. Use **Start** to launch the selected assigned app.
5. Use **Desktop** to create/remove a desktop entry for the selected app.

The Status table shows application, interface, user, mark, table, and priority.

## CLI usage

List active interfaces:

```bash
sudo python3 cli.py networks
```

List current routing rules:

```bash
sudo python3 cli.py rules
```

Assign an app to an interface:

```bash
sudo python3 cli.py assign --app "/usr/bin/yandex-browser-stable" --iface enp0s31f6
```

Start an assigned app:

```bash
sudo python3 cli.py start --app "/usr/bin/yandex-browser-stable"
```

Deassign an app:

```bash
sudo python3 cli.py deassign --app "/usr/bin/yandex-browser-stable"
```

Reset all Lemux rules:

```bash
sudo python3 cli.py reset
```

Desktop entries:

```bash
sudo python3 cli.py desktop list
sudo python3 cli.py desktop create --app "/usr/bin/yandex-browser-stable"
sudo python3 cli.py desktop delete --app "/usr/bin/yandex-browser-stable"
sudo python3 cli.py desktop set-path --app "/usr/bin/yandex-browser-stable" --path /home/USER/Desktop/yandex-lemux.desktop
```

Trace test:

```bash
sudo python3 cli.py trace --app "/usr/bin/yandex-browser-stable" --iface enp0s31f6 --timeout 5 --url https://example.org
```

## How it works

1. Lemux creates (or reuses) a dedicated system user for the app.
2. nftables marks packets for that uid (fwmark).
3. ip rule routes marked packets via a dedicated routing table for the selected interface.
4. The app runs as that user, with audio and desktop integration handled at launch.

## Notes

- `pkexec` is used to run the root-only CLI from desktop entries.
- The desktop entry uses `LEMUX_INVOKING_USER=%u` so the correct user context is preserved.
- For apps with command-line arguments, Lemux stores `binary` + `arguments` separately to keep routing stable.

## License

Creative Commons Attribution-NonCommercial 4.0 License

---

Lemux is a deeply rewritten fork of intermux: https://github.com/Rishi-Bhati/intermux
