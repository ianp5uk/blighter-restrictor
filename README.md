<!--
Blighter Restrictor - README.
Purpose: how the system works, how to install the parent app and the child
component (Ubuntu or Windows laptops), day-to-day use, limits, and how to
build the packages (Linux and Windows).
-->

# Blighter Restrictor 1.2.2

Monitor and restrict your children's web access on their Ubuntu 26.04 or
Windows 10/11 laptops.
Each child's laptop runs Squid as a local web filter. The parent app (Linux or
Windows) logs in to each laptop over the home network to change the rules and
read the activity log.

## How it works

```
 Parent PC (Linux / Windows)                Child laptop (Ubuntu 26.04 / Windows)
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
* On **Windows** laptops the firewall covers the **whole laptop** (every
  account, including yours), because Windows can't reliably filter outgoing
  traffic per account. See section 1b.
* **Blocked sites show a plain "This site isn't available" page** on plain
  http sites. It doesn't mention Squid, a proxy, filtering or parents, and
  Squid's own headers (`Server`, `Via`, `X-Cache`, `X-Squid-Error`) are
  removed. Secure (https) sites show the browser's own error instead (for
  example "The proxy server is refusing connections"); nothing on the laptop
  can change that.
* **Discord** has its own per-child switch, *Allow Discord* (Rules tab). It
  covers Discord's web addresses and, for voice and video calls, outgoing
  UDP 50000-65535. It wins over both lists. Note: while Discord is allowed,
  that UDP range is open to **any** program, so a child who is an
  administrator could run a VPN on a port in that range. For tight control,
  make the child a standard user, or switch Discord off.

## 1. Set up each child's laptop

Do this as an administrator on the child's laptop. The child's own account
must **not** be an administrator.

```bash
sudo apt install ./blighter-child_1.2.2_all.deb     # also installs squid, openssh-server, nftables if missing
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
* Discord is allowed by default; switch it off or on in the parent app (Rules
  tab, *Allow Discord*), or with `sudo blighter-setup <child> --no-discord`.
  Running setup again keeps the earlier choice.
* Upgrading from an earlier version (`sudo apt install ./blighter-child_1.2.2_all.deb`)
  rewrites the Squid rules with the new settings (neutral error page, Discord
  switch) and keeps the lists.
* To undo everything: `sudo blighter-setup --remove` (or `sudo apt remove blighter-child`).

## 1b. Set up a child's Windows 10/11 laptop

Use 64-bit Windows 10 or 11 (Home or Pro). Sign in to a **parent
administrator account** on the laptop, not the child's.

1. Copy `blighter-child-windows-1.2.2.zip` to the laptop and **unzip it**
   (right-click → *Extract All*). Don't run it from inside the zip.
2. Double-click **Install Blighter Child.cmd** and accept the Windows prompt.
3. Setup says first that it takes **15-30 minutes** and lists the slow steps,
   then asks *Start now?*. Answer *n* if you don't have time; nothing is changed.
4. Pick the child's account from the list, say whether to allow Discord, then
   choose a password (10+ characters) for the hidden **blighter**
   administrator account. You enter this password in the parent app.

While it runs, each step shows how long it usually takes and, afterwards, how
long it took. Slow steps print a *still working* line every 30 seconds, and
the laptop is kept awake. If setup stops part-way, through an error or
Ctrl+C, it offers to undo what it has done so far (the default is yes). If the
laptop is switched off part-way, running *Install Blighter Child.cmd* again
offers to finish or undo, and the parent app's Laptop tab warns that setup
didn't finish. To update a laptop from an earlier version, run the new
*Install Blighter Child.cmd* over the top. Its saved "before" state is kept.

Setup then:
* **before changing anything else**, creates a Windows restore point called
  *Before Blighter Restrictor*. It switches on System Protection for C: if it's
  off. It also saves the laptop's current settings in
  `C:\ProgramData\BlighterChild\state\pre-install.json`: firewall defaults,
  browser proxy policies, the child's own proxy setting, and whether OpenSSH,
  Squid and the `blighter` account already existed.
* downloads and installs **Squid for Windows** (Diladele, Squid 7.8) if it's
  missing, and locks `C:\Squid` so only administrators can change it.
  Folders made at the root of C: are otherwise changeable by every signed-in
  user, which would let a child edit the filter.
* copies the helper, with its own private copy of Python, to
  `C:\ProgramData\BlighterChild` (locked the same way)
* creates the hidden `blighter` administrator account and switches on
  Windows' own **OpenSSH Server**
* saves the existing `squid.conf` as `squid.conf.pre-blighter-<date>` and
  installs its own. Squid for Windows can't read Windows' DNS settings, so
  it uses 1.1.1.1 and 8.8.8.8. To use others, run
  `blighter-setup.ps1 -DnsServers "9.9.9.9 149.112.112.112"`.
* sets up the **whole-laptop firewall**. Outgoing traffic is blocked by
  default. Only Squid, Windows' own services (DNS, DHCP, time, Windows
  Update, Defender, network check, Microsoft account sign-in, Edge updates),
  ping and UDP 50000-65535 (Discord voice) can go out. All other "allow
  outgoing" rules (Store apps, Xbox, games) are switched off, and their names
  are recorded so removal can switch them back on.
* allows incoming SSH only from the local network, and only while Windows
  calls the network **Private**. If the home Wi-Fi is set to *Public*, setup
  offers to change it.
* points the child's proxy setting, and the Edge, Chrome and Firefox proxy
  policies, at Squid (127.0.0.1:3128), and greys out Windows' proxy page
* adds a scheduled task, **Blighter Restrictor\Enforce**. As SYSTEM, at start-up,
  at every log-on and every 10 minutes, it repairs the firewall and proxy
  settings and restarts Squid or SSH if they've stopped. A second task starts
  a new Squid log each night (14 old logs are kept).

**Warning - children who are administrators.** On many family PCs the child's
account is an administrator, often because it was the first or only account.
Setup and the parent app both warn about this. An administrator can switch
off the firewall, stop Squid, delete the task or uninstall everything. The
filter still works, and the parent app shows what's in force, but nothing on
the laptop can stop an administrator who goes looking. To fix it, create (or
keep) a separate parent administrator account, sign in to it, then in
*Settings → Accounts → Other users* change the child's account to *Standard
user*.

Notes for Windows:
* Discord (desktop app) uses Windows' proxy setting for text. Voice and video
  use the UDP exception. Both follow the *Allow Discord* switch in the
  parent app's Rules tab (setup asks for the starting value; `-NoVoice`
  blocks it without asking).
* Store apps (Microsoft Store, Xbox, Minecraft from the Store, Mail) are
  usually **offline**. Windows doesn't let them use a proxy on the same
  laptop, and their firewall rules are switched off. That also stops the child
  installing Store apps.
* Office, Chrome and other programs that update themselves through their own
  background service can't update while the filter is on. Windows Update,
  Defender and Edge updates still work.
* Browsers show "managed by your organisation". That's the proxy policy.
* **Pause Blighter Child.cmd** (in `C:\ProgramData\BlighterChild`) switches
  filtering off without uninstalling. The firewall, browser policies and the
  child's proxy go back to how they were before setup, and the self-repair task
  is switched off. The parent app can still connect, and its Laptop tab shows
  *PAUSED*. Use it to check whether a problem is caused by Blighter Restrictor.
  **Resume Blighter Child.cmd** switches filtering back on.
* **Remove Blighter Child.cmd** (from the zip or from
  `C:\ProgramData\BlighterChild`) puts the laptop back as it was before setup:
  * firewall defaults, the switched-off rules, browser policies and the child's
    proxy setting are restored from the saved record
  * networks that setup marked Private go back to Public
  * anything setup added is removed: it deletes the `blighter` account and its
    profile, stops, disables and uninstalls OpenSSH Server, uninstalls Squid,
    and deletes `C:\ProgramData\BlighterChild`. It asks before each; the
    default answer is yes. Anything that was there before setup is left as it
    was.
  * If anything still behaves differently, use System Restore and pick
    *Before Blighter Restrictor*.
* Emergency fix if the scripts are missing. In an administrator PowerShell, run
  `Get-ScheduledTask -TaskPath "\Blighter Restrictor\" | Unregister-ScheduledTask -Confirm:$false`
  then `Set-NetFirewallProfile -All -DefaultOutboundAction NotConfigured`.
  This restores internet straight away.

## 2. Install the parent app

**Ubuntu:** `sudo apt install ./blighter-restrictor_1.2.2_all.deb`, then start
*Blighter Restrictor* from the app menu (or run `blighter-restrictor`).

**Windows:** run `BlighterRestrictor-Setup-1.2.2.exe` (see "Building for
Windows" below). It isn't signed, so Windows SmartScreen shows a warning:
click *More info → Run anyway*.

## 3. Using the app

* **Add** a child: name, laptop IPv4 address, the child's username (as given to
  the setup), admin login `blighter` and its password. *Test connection*
  checks it, says whether the laptop is Ubuntu or Windows (it's recognised
  automatically), and warns if the child is an administrator. Passwords are kept in the system keyring (GNOME Keyring /
  Windows Credential Manager).
* **Rules tab:** pick the mode and edit the lists, one domain per line:
  * `.example.com` – the site **and all subdomains** (normal choice)
  * `example.com` – that exact name only
  * `# text` – a comment
  * `*.example.com` and pasted web addresses are converted automatically.
    Duplicates, and entries already covered by a `.domain` entry, are removed.
  * **Allow Discord** (next to the mode) switches Discord on or off for that
    child, whatever the lists say. Discord lines typed into a list are
    pointed out, because they have no effect. Laptops with a child version
    older than 1.2.2 show the switch greyed out.
  * **Apply to laptop** sends the lists and the Discord switch. The laptop
    checks them with Squid and reloads it. If Squid rejects them, the
    previous rules are restored automatically.
* **Activity tab:** the laptop's Squid log, newest first, with filters (time,
  site, blocked only), *Include older logs*, *Live* refresh every 5 seconds,
  and a *Summary by site* view. **Right-click** a row to add that site, or its
  parent domain, to the Block or Allow list. Then press *Apply to laptop* in
  the Rules tab.
  Tip for *Block all, allow some*: sites often need extra domains for images
  and scripts (e.g. `.gstatic.com`, `.cloudfront.net`). Tick *Blocked only*
  to find and allow them.
* **Laptop tab:** what is actually in force on the laptop, read back from it:
  health checks (system, filtered user, whether the child is an
  administrator, Squid running, firewall active, proxy locked), the generated
  rules, both lists, `squid.conf` and the firewall rules.
  The settings appear straight away; the health checks follow (a few
  seconds; on Windows up to a minute). *Reload Squid* rewrites the generated
  rules and re-reads the configuration on demand.

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
* For blocked HTTPS sites the browser shows its own proxy error, not the
  "This site isn't available" page, and that error mentions a proxy. Windows'
  proxy settings also say "managed by your organisation". A curious child
  can therefore still find out that a filter is in place.
* DNS (port 53) stays open for the child's account. That's harmless for web
  filtering, which is done on site names by Squid.
* Windows: a child who is an administrator can undo everything (see 1b).
  Booting from USB or reinstalling Windows gets round it too. A BIOS/UEFI
  password and BitLocker close that gap if needed.
* Windows: the Windows component is checked automatically on GitHub's Windows Server
  machines, not on a real family laptop. Check it on the first laptop before
  relying on it.

## Building

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
4. Result: `dist\BlighterRestrictor-Setup-1.2.2.exe`. Install it on your wife's PC.
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
cryptography, bcrypt, PyNaCl), each under its own licence. Ubuntu child laptops
use Squid (GPL-2.0-or-later) and nftables from Ubuntu. Windows child laptops use
Squid for Windows from Diladele B.V. (GPL, downloaded during setup) and the
Windows child package bundles the python.org embeddable Python (PSF License).

## Files

| Path | Purpose |
|---|---|
| `common/domains.py` | Domain validation and the Discord switch rules, shared by the app and the laptop helpers |
| `common/blockpage.py` | The neutral error page and Squid header settings, shared by both laptop helpers |
| `parent/blighter_parent/` | The GUI app (Qt / PySide6, Paramiko SSH, keyring) |
| `parent/packaging/` | Ubuntu launcher, menu entry and package control file |
| `child/files/usr/sbin/blighter-setup` | One-time laptop setup / removal |
| `child/files/usr/sbin/blighter-apply` | The only root command the app may run |
| `child/files/usr/sbin/blighter-firewall` | Child-only nftables firewall |
| `child/files/usr/share/blighter-child/squid.conf` | Managed Squid configuration |
| `child-windows/blighter-setup.ps1` | Windows laptop setup / removal |
| `child-windows/blighter-system.ps1` | Windows whole-laptop firewall, proxy policies, self-repair task |
| `child-windows/blighter-apply.py` / `.cmd` | Windows helper the app runs over SSH (same commands as Ubuntu's) |
| `child-windows/squid.conf` | Managed Squid configuration for Squid for Windows |
| `child-windows/*.cmd` | Double-click install / pause / resume / remove |
| `build-windows-child.sh` | Builds the Windows child zip |
| `windows/` | Windows build script, installer definition, icon (parent app) |
| `LICENSE` | GNU General Public License v3.0 |
