<!--
Blighter Restrictor - README.
Purpose: how the system works, how to install the parent app and the child
package, day-to-day use, limits, and how to build the packages (Linux and Windows).
-->

# Blighter Restrictor 1.1.1

Monitor and restrict your children's web access on their Ubuntu 26.04 laptops.
Each child's laptop runs Squid as a local web filter. The parent app (Linux or
Windows) logs in to each laptop over the home network to change the rules and
read the activity log.

## How it works

```
 Parent PC (Linux / Windows)                Child laptop (Ubuntu 26.04)
 ┌──────────────────────────┐   SSH, pw   ┌──────────────────────────────────┐
 │ Blighter Restrictor app  │────────────▶│ blighter account                  │
 │  Rules / Activity / Laptop│            │  └ sudo blighter-apply (only this)│
 └──────────────────────────┘             │ Squid 127.0.0.1:3128  ── filters  │
                                          │ Firewall: child's account may     │
                                          │  only reach Squid, DNS, UDP voice │
                                          └──────────────────────────────────┘
```

* **Filtering is by domain name.** HTTPS isn't decrypted, so the log shows the
  sites visited (e.g. `www.youtube.com`) but not individual pages.
* **Modes:** *Allow all, block some* uses the Block list. *Block all, allow
  some* uses the Allow list. Both lists are always kept.
* **No bypass by changing proxy settings.** A firewall applied only to the
  child's account rejects all direct internet traffic. The only exceptions are
  DNS and UDP 50000-65535 (Discord voice/video). Steam, other game clients,
  VPNs and so on don't work for that account.
* Filtering still works when the laptop is away from home. Changes and log
  viewing only work on the home network.

## 1. Set up each child's laptop

Do this as an administrator on the child's laptop. The child's own account
must **not** be an administrator.

```bash
sudo apt install ./blighter-child_1.1.1_all.deb     # also installs squid, openssh-server, nftables if missing
sudo blighter-setup <child-username>                # e.g. sudo blighter-setup tom
```

Setup asks you to choose a password for the **blighter** admin account (you
enter it in the parent app). It then:
* saves the existing `/etc/squid/squid.conf` as `squid.conf.pre-blighter-<date>` and installs its own
* allows SSH password login for the `blighter` account only, and switches SSH on
* starts the child-only firewall (`blighter-firewall.service`, started at every boot)
* sets the desktop proxy to 127.0.0.1:3128 and locks it
* makes the Discord launcher (.deb or snap) use the proxy, if Discord is installed

At the end it prints the laptop's IPv4 address. **Reserve that address in your
router's DHCP settings** so it doesn't change. The child must log out and back
in once.

Notes:
* If you install Discord later, run `sudo blighter-setup <child-username>` again.
* Discord in Firefox works without any of this. The Flatpak version of Discord
  isn't handled.
* To turn off Discord voice (UDP) for a child: `sudo blighter-setup <child> --no-voice`.
* To undo everything: `sudo blighter-setup --remove` (or `sudo apt remove blighter-child`).

## 2. Install the parent app

**Ubuntu:** `sudo apt install ./blighter-restrictor_1.1.1_all.deb`, then start
*Blighter Restrictor* from the app menu (or run `blighter-restrictor`).

**Windows:** run `BlighterRestrictor-Setup-1.1.1.exe` (see "Building for
Windows" below). It isn't signed, so Windows SmartScreen shows a warning:
click *More info → Run anyway*.

## 3. Using the app

* **Add** a child: name, laptop IPv4 address, the child's username (as given to
  `blighter-setup`), admin login `blighter` and its password. *Test connection*
  checks it. Passwords are kept in the system keyring (GNOME Keyring /
  Windows Credential Manager).
* **Rules tab:** pick the mode and edit the lists, one domain per line:
  * `.example.com` – the site **and all subdomains** (normal choice)
  * `example.com` – that exact name only
  * `# text` – a comment
  * `*.example.com` and pasted web addresses are converted automatically.
    Duplicates, and entries already covered by a `.domain` entry, are removed.
  * **Apply to laptop** sends the lists. The laptop checks them with Squid and
    reloads it. If Squid rejects them, the previous rules are restored
    automatically.
* **Activity tab:** the laptop's Squid log, newest first, with filters (time,
  site, blocked only), *Include older logs*, *Live* refresh every 5 seconds,
  and a *Summary by site* view. **Right-click** a row to add that site, or its
  parent domain, to the Block or Allow list. Then press *Apply to laptop* in
  the Rules tab.
  Tip for *Block all, allow some*: sites often need extra domains for images
  and scripts (e.g. `.gstatic.com`, `.cloudfront.net`). Tick *Blocked only*
  to find and allow them.
* **Laptop tab:** what is actually in force on the laptop, read back from it:
  health checks (Squid running, firewall active, proxy locked, filtered
  user), the generated rules, both lists, `squid.conf` and the firewall table.
  *Reload Squid* re-reads the configuration on demand.

* **Logging out:** a child shown in **bold** has an open SSH session to their
  laptop. *Log out* closes it for the selected child, and *File → Log out of
  all laptops* (Ctrl+L) closes them all. Sessions also close automatically after
  5 minutes without use (unless *Live* is on) and whenever the app is closed.
  Any later action logs in again automatically.
* **Text size:** *View → Larger text / Smaller text / Normal text size*
  (Ctrl +, Ctrl −, Ctrl 0), from 80% to 300%. The size is remembered.

Settings are stored in `~/.config/blighter-restrictor/` (Linux) or
`%APPDATA%\BlighterRestrictor\` (Windows). Each PC keeps its own list of
children and passwords, so on your wife's PC add the children again.

## Limits

* A determined child with physical access could get round this using recovery
  mode or a USB boot. Setting a GRUB password and a BIOS/UEFI password closes
  that gap if it's needed later.
* For blocked HTTPS sites the browser shows a proxy error, not a "blocked" page.
* DNS (port 53) stays open for the child's account. That's harmless for web
  filtering, which is done on site names by Squid.

## Building

### Linux packages (on Ubuntu)
```bash
./build-debs.sh        # -> dist/blighter-restrictor_<ver>_all.deb and dist/blighter-child_<ver>_all.deb
```
Run the parent app from source without installing:
`sudo apt install python3-pyside6.qtwidgets python3-paramiko python3-keyring`
then `cd parent && /usr/bin/python3 -m blighter_parent`.

### Building for Windows
The GitHub repository builds the Windows installer automatically
(`.github/workflows/windows.yml`, on GitHub's Windows machines). To build by hand
on a Windows 10/11 PC instead:
1. Install **Python 3.12 or newer** from python.org (tick "Add python.exe to PATH").
2. Install **Inno Setup 6** from https://jrsoftware.org/isdl.php (for the single Setup.exe).
3. Copy this whole project folder to the PC, open PowerShell in it and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\build_windows.ps1
   ```
4. Result: `dist\BlighterRestrictor-Setup-1.1.1.exe`. Install it on your wife's PC.
   (Without Inno Setup you get a runnable folder `dist\BlighterRestrictor\` instead.)

## Licence

Copyright (C) 2026 Ways Property.

Blighter Restrictor is free software, licensed under the **GNU General Public
License v3.0 or later** (`GPL-3.0-or-later`); the full text is in [LICENSE](LICENSE).
You may use, copy, modify and redistribute it. If you distribute it, or a
modified version, whether free or for a fee, you must do so under the same
licence and make the complete source code available to the people you give it
to. It comes with **no warranty**.

Libraries used: PySide6 / Qt (LGPL-3.0), Paramiko (LGPL-2.1-or-later),
keyring (MIT). The Windows build also bundles their dependencies (e.g.
cryptography, bcrypt, PyNaCl), each under its own licence. The child laptops use
Squid (GPL-2.0-or-later) and nftables from Ubuntu.

## Files

| Path | Purpose |
|---|---|
| `common/domains.py` | Domain validation shared by the app and the laptop helper |
| `parent/blighter_parent/` | The GUI app (Qt / PySide6, Paramiko SSH, keyring) |
| `parent/packaging/` | Ubuntu launcher, menu entry and package control file |
| `child/files/usr/sbin/blighter-setup` | One-time laptop setup / removal |
| `child/files/usr/sbin/blighter-apply` | The only root command the app may run |
| `child/files/usr/sbin/blighter-firewall` | Child-only nftables firewall |
| `child/files/usr/share/blighter-child/squid.conf` | Managed Squid configuration |
| `windows/` | Windows build script, installer definition, icon |
| `LICENSE` | GNU General Public License v3.0 |
