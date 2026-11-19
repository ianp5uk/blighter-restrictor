# Building
Bit of information here for those who want to roll their own. It will probably
barf on a different environment but if you're doing this you are probably able
to correct any issues.

### Linux packages (on Ubuntu)
```bash
./build-debs.sh        # -> dist/blighter-restrictor_<ver>_all.deb and dist/blighter-child_<ver>_all.deb
```
Run the parent app from source without installing:
`sudo apt install python3-pyside6.qtwidgets python3-paramiko python3-keyring`
then `cd parent && /usr/bin/python3 -m blighter_parent`.

### Windows child package (on Linux)
```bash
./build-windows-child.sh   # -> dist/blighter-child-windows-<ver>.zip
```
It bundles the official python.org "embeddable" Python for the helper, so
nothing has to be compiled on Windows. GitHub also builds the zip and tests it
on a Windows machine (jobs `child-package` and `child-test`).

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
4. Result: `dist\BlighterRestrictor-Setup-1.2.4.exe`. Install it on the parent's Windows PC.
   (Without Inno Setup you get a runnable folder `dist\BlighterRestrictor\` instead.)

## Licence

Copyright (C) 2026 Ian Packer.

Blighter Restrictor is free software, licensed under the **GNU General Public
License v3.0 or later** (`GPL-3.0-or-later`); the full text is in [LICENSE](LICENSE).
You may use, copy, modify and redistribute it. If you distribute it, or a
modified version, whether free or for a fee, you must do so under the same
licence and make the complete source code available to the people you give it
to. It comes with **no warranty**.

Libraries used: PySide6 / Qt (LGPL-3.0), Paramiko (LGPL-2.1-or-later),
keyring (MIT). The Windows build also bundles their dependencies (e.g.
cryptography, bcrypt, PyNaCl), each under its own licence. Ubuntu child PCs
use Squid (GPL-2.0-or-later) and nftables from Ubuntu. Windows child PCs use
Squid for Windows from Diladele B.V. (GPL, downloaded during setup) and the
Windows child package bundles the python.org embeddable Python (PSF License).

## Files

| Path | Purpose |
|---|---|
| `common/domains.py` | Domain validation and the Discord switch rules, shared by the app and the PC helpers |
| `common/blockpage.py` | The neutral error page and Squid header settings, shared by both PC helpers |
| `parent/blighter_parent/` | The GUI app (Qt / PySide6, Paramiko SSH, keyring) |
| `parent/packaging/` | Ubuntu launcher, menu entry and package control file |
| `child/files/usr/sbin/blighter-setup` | One-time PC setup / removal |
| `child/files/usr/sbin/blighter-apply` | The only root command the app may run |
| `child/files/usr/sbin/blighter-firewall` | Child-only nftables firewall |
| `child/files/usr/share/blighter-child/squid.conf` | Managed Squid configuration |
| `child-windows/blighter-setup.ps1` | Windows PC setup / removal |
| `child-windows/blighter-system.ps1` | Windows whole-PC firewall, proxy policies, self-repair task |
| `child-windows/blighter-apply.py` / `.cmd` | Windows helper the app runs over SSH (same commands as Ubuntu's) |
| `child-windows/squid.conf` | Managed Squid configuration for Squid for Windows |
| `child-windows/*.cmd` | Double-click install / pause / resume / remove |
| `build-windows-child.sh` | Builds the Windows child zip |
| `windows/` | Windows build script, installer definition, icon (parent app) |
| `LICENSE` | GNU General Public License v3.0 |
