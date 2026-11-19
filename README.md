<!--
Blighter Restrictor - README.
Purpose: how the system works, how to install the parent app and the child
component (Ubuntu or Windows PCs), day-to-day use, limits, and how to
build the packages (Linux and Windows).
-->

# Blighter Restrictor 1.2.4

Monitor and restrict your children's web access on their Ubuntu 26.04 or
Windows 10/11 PCs.
The parent app (Linux or Windows) logs in to each PC over the home network to
change the rules and read the activity log. You can block everything and allow a
few web sites or the oposite, allow all and block a few. You can pause the
restrictions. 

## Support this project

Blighter Restrictor is free to use. If it helps your family, donations are
very welcome and help pay for new features and fixes:

* [Ko-fi](https://ko-fi.com/ianp5) - one-off or regular donations, no account needed
* [GitHub Sponsors](https://github.com/sponsors/ianp5uk) - for GitHub users

## IMPORTANT

This application is supplied free of charge for now and you use it at your own risk. It has
been subject to automated testing and I am personally using it. That said please
ensure you have backups of any critical information on your device. You should have
this regardless. It is designed to operate on closed networks such as behind a home
router, as such, for convenience, it uses only password security, no MFA etc.

## Problems, feedback & suggestions

I do not promise to respond to everything but please do report problems, make
suggestions and give feedback. You can report them here:

* [Problems, feedback & suggestions](https://github.com/ianp5uk/blighter-restrictor/issues)

# Installation

#### ** You need to allocate an hour+ to set this up. **

More details further down.

You can install onto the child's PC. It needs an
x86 or x64 Intel or AMD processor. It has not been run or tested on ARM processors.
It might just work on ARM, I have no idea. It has not been tested on tablets.

For this to work properly, you will need to change network configurations. You
need to move the child's PC to use a static IP address and fixed hardware MAC
address. Then your router needs to be switched to use a static address for the
child's PC. This is because as standard router & PC will change their address 
periodically, this makes it difficult for the app to communicate. If you do not
know how to do this, please work with your friendly AI; ChatGPT, Google, Claude
whatever your preference.

The overall process is; install child components on their PCs while logged on
with Admin / root rights, install parent component on your PC. It expects both
PC's to be on a home network and able to communicate freely. Privacy & security
was not designed for public networks as this would make it a pain on home networks
secured behind the router's firewall. If your child has Admin rights on their PC,
it is possible they could subvert the restrictions, if they are either highly motivated
or IT smart. If both you're in for a cat and mouse game!

**You will get warnings on Windows during install because this software is not yet
certified.** This requires paying people and having a certificate of origin. This
will be done if there is sufficient interest.

## How it works

```
 Parent PC (Linux / Windows)                Child PC (Linux / Windows)
 ┌──────────────────────────┐   SSH, pw   ┌──────────────────────────────────┐
 │ Blighter Restrictor app  │────────────▶│ blighter account                  │
 │  Rules / Activity / PC   │             │                                   │
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
* **>>> Filtering still works when the PC is away from home. Changes and log
  viewing only work on the home network. <<<**
* On **Windows** PCs the firewall covers the **whole PC** (every
  account, including yours), because Windows can't reliably filter outgoing
  traffic per account. See section 1b.
* **Blocked sites show a plain "This site isn't available" page** on plain
  http sites. It doesn't mention Squid, a proxy, filtering or parents, and
  Squid's own headers (`Server`, `Via`, `X-Cache`, `X-Squid-Error`) are
  removed. Secure (https) sites show the browser's own error instead (for
  example "The proxy server is refusing connections"); nothing on the PC
  can change that.
* **The home network is not filtered.** Blighter controls internet access
  only. With *Allow home network access* on (the default), the PC can
  reach printers, NAS drives and other devices on the home network's
  subnet(s) directly, and web pages on them go through Squid without being
  blocked. Setup records the private network (10.x, 172.16-31.x or 192.168.x)
  the PC is on; the Rules tab can change it, including to other ranges
  (with a warning, because websites in a non-private range would bypass the
  filter).
* **Discord** has its own per-child switch, *Allow Discord* (Rules tab). It
  covers Discord's web addresses and, for voice and video calls, outgoing
  UDP 50000-65535. It wins over both lists. Note: while Discord is allowed,
  that UDP range is open to **any** program, so a child who is an
  administrator could run a VPN on a port in that range. For tight control,
  make the child a standard user, or switch Discord off.
* **Opera downloads are blocked** by default (*Block Opera downloads*, Rules
  tab). Opera has a free built-in VPN that can't be switched off, so Squid
  refuses opera.com and Opera's download servers. An Opera that's already
  installed isn't removed. Switch it off per child if you want Opera.
* **VPNs that need a paid subscription** (for example Brave's) are not
  specially blocked. Blighter assumes a parent who pays for one has chosen
  to let the child use it.


## 1a. Set up a child's Linux PC

Do this as an administrator on the child's PC. The child's own account
should ideally **not** be an administrator. 

```bash
sudo apt install ./blighter-child_1.2.4_all.deb     # also installs squid, openssh-server, nftables if missing
sudo blighter-setup <child-username>                # e.g. sudo blighter-setup tom
```

Setup asks you to choose a password for the **blighter** admin account (you
enter it in the parent app). It then:
* saves the existing `/etc/squid/squid.conf` as `squid.conf.pre-blighter-<date>` and installs its own
* allows SSH password login for the `blighter` account only, and switches SSH on
* starts the child-only firewall (`blighter-firewall.service`, started at every boot)
* sets the desktop proxy to 127.0.0.1:3128 and locks it
* makes the Discord launcher (.deb or snap) use the proxy, if Discord is installed

At the end it prints the PC's IPv4 address. **Reserve that address in your
router's DHCP settings** so it doesn't change. The child must log out and back
in once.

Notes:
* Discord is allowed by default; switch it off or on in the parent app (Rules
  tab, *Allow Discord*).
  Running setup again keeps the earlier choice.
* Upgrading from an earlier version rewrites the Squid rules with the new settings
  (neutral error page, Discord switch) and keeps the lists. 
* If Squid on the PC already looks set up by something else, setup stops
  before changing anything and asks whether to replace Squid's settings (add
  `--replace-squid` to skip the question).  The old `squid.conf` is saved and put
  back on removal.
* To undo everything: `sudo blighter-setup --remove` (or `sudo apt remove blighter-child`).

## 1b. Set up a child's Windows 10/11 PC

Use 64-bit Windows 10 or 11 (Home or Pro). Sign in to a **parent
administrator account** on the child's PC, not the child's account.

1. Copy `BlighterChild-Setup-1.2.5.exe` to the child's PC.
2. Double-click the setup exe and follow the directions.
3. It may take a while on some steps, do not give up unless sure it's failed.
4. Pick the child's account from the list, then
   choose a password (10+ characters) for the hidden **blighter**
   administrator account. You enter this password in the parent app.

While it runs, each step shows how long it usually takes and, afterwards, how
long it took. Slow steps print an indicator line every 30 seconds, and
the PC is kept awake. If setup stops part-way, through an error, it offers
to undo what it has done so far (the default is yes). If the PC is switched
off part-way, running setup again offers to finish or undo, and the parent
app's PC tab warns that setup didn't finish. To update a PC from an earlier
version, run the new setup over the top. Its saved "before" state is kept.

Setup then:
* **before changing anything else**, creates a Windows restore point called
  *Before Blighter Restrictor*. It switches on System Protection for C: if it's
  off. It also saves the PC's current settings in
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
* sets up the **whole-PC firewall**. Outgoing traffic is blocked by
  default. Only Squid, Windows' own services (DNS, DHCP, time, Windows
  Update, Defender, network check, Microsoft account sign-in, Edge updates),
  ping, UDP 50000-65535 (Discord voice) and the home network (printers,
  NAS...) can go out. All other "allow
  outgoing" rules (Store apps, Xbox, games) are switched off, and their names
  are recorded so removal can switch them back on.
* allows incoming SSH only from the local network or the recorded home
  network (even with home network access off), and only while Windows
  calls the network **Private**. If the home Wi-Fi is set to *Public*, setup
  offers to change it.
* points the child's proxy setting, and the Edge, Chrome, Brave, Vivaldi and
  Firefox proxy
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
the PC can stop an administrator who goes looking. To fix it, create (or
keep) a separate parent administrator account, sign in to it, then in
*Settings → Accounts → Other users* change the child's account to *Standard
user*.

Notes for Windows:
* If the parent app can't connect (it times out) although the PC is on
  and on the home Wi-Fi, turn the PC's Wi-Fi off and on, then try again.
  Windows occasionally works out its "local network" wrongly after a cold
  start; since 1.2.4 SSH is also allowed from the recorded home network, so
  this should be rare.
* Discord (desktop app) uses Windows' proxy setting for text. Voice and video
  use the UDP exception. Both follow the *Allow Discord* switch in the
  parent app's Rules tab (setup asks for the starting value; `-NoVoice`
  blocks it without asking).
* Store apps (Microsoft Store, Xbox, Minecraft from the Store, Mail) are
  usually **offline**. Windows doesn't let them use a proxy on the same
  PC, and their firewall rules are switched off. That also stops the child
  installing Store apps.
* Office, Chrome and other programs that update themselves through their own
  background service can't update while the filter is on. Windows Update,
  Defender and Edge updates still work.
* Browsers show "managed by your organisation". That's the proxy policy.
* **Pause Blighter Child.cmd** (in `C:\ProgramData\BlighterChild`) switches
  filtering off without uninstalling. The firewall, browser policies and the
  child's proxy go back to how they were before setup, and the self-repair task
  is switched off. The parent app can still connect, and its PC tab shows
  *PAUSED*. Use it to check whether a problem is caused by Blighter Restrictor.
  **Resume Blighter Child.cmd** switches filtering back on.
* **Remove Blighter Child.cmd** (from the zip or from
  `C:\ProgramData\BlighterChild`) puts the PC back as it was before setup:
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

**Ubuntu:** `sudo apt install ./blighter-restrictor_1.2.5_all.deb`, then start
*Blighter Restrictor* from the app menu (or run `blighter-restrictor`).

**Windows:** run `BlighterRestrictor-Setup-1.2.5.exe` (see "Building for
Windows" below). It isn't signed, so Windows SmartScreen shows a warning:
click *More info → Run anyway*.

## 3. Using the app

* **Add** a child: name, PC IPv4 address, the child's username (as given to
  the setup), admin login `blighter` and its password. Each PC can be
  listed only once (same IP address and child username); a PC already
  listed twice is pointed out when the app starts, so you can remove the
  extra entry. *Test connection*
  checks it, says whether the PC is Ubuntu or Windows (it's recognised
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
    pointed out, because they have no effect. PCs with a child version
    older than 1.2.2 show the switch greyed out.
  * **Block Opera downloads** (next to Allow Discord, on by default) stops
    Opera being downloaded. PCs older than 1.2.4 show it greyed out.
  * **Apply to PC** sends the lists and the switches. The PC
    checks them with Squid and reloads it. If Squid rejects them, the
    previous rules are restored automatically.
* **Activity tab:** the PC's Squid log, newest first, with filters (time,
  site, blocked only), *Include older logs*, *Live* refresh every 5 seconds,
  and a *Summary by site* view. **Right-click** a row to add that site, or its
  parent domain, to the Block or Allow list. Then press *Apply to PC* in
  the Rules tab.
  Tip for *Block all, allow some*: sites often need extra domains for images
  and scripts (e.g. `.gstatic.com`, `.cloudfront.net`). Tick *Blocked only*
  to find and allow them.
* **Allow home network access** (Rules tab, under the mode) switches the
  home network on or off for that PC and shows its subnet(s), e.g.
  `192.168.1.0/24 (Home Wi-Fi)`. *Use current network* asks the PC
  which network it's on now. Applied with *Apply to PC*.
* **PC tab:** what is actually in force on the PC, read back from it:
  health checks (system, filtered user, whether the child is an
  administrator, Squid running, firewall active, proxy locked), the generated
  rules, both lists, `squid.conf` and the firewall rules.
  The settings appear straight away; the health checks follow (a few
  seconds; on Windows up to a minute). *Reload Squid* rewrites the generated
  rules and re-reads the configuration on demand.
  **Pause filtering** switches filtering off on that PC, and **Resume
  filtering** switches it back on. Use them to check whether a problem is
  caused by Blighter Restrictor. While paused the child has **open,
  unfiltered internet access**: the PC tab shows a red banner and the
  children list shows "- PAUSED" in red. The app can still connect while
  paused. (On Windows this is the same as the PC's *Pause / Resume
  Blighter Child.cmd*. On Ubuntu, Squid lets everything through and the child
  firewall stands down until Resume, even across restarts.)
* While the app waits for a PC, the status bar shows **Working…** with a
  moving bar, and that tab's buttons are greyed out. Windows PCs take a
  few seconds per request; Ubuntu PCs answer almost at once.

* **Logging out:** a child shown in **bold** has an open SSH session to their
  PC. *Log out* closes it for the selected child, and *File → Log out of
  all PCs* (Ctrl+L) closes them all. Sessions also close automatically after
  5 minutes without use (unless *Live* is on) and whenever the app is closed.
  Any later action logs in again automatically.
* **Text size:** *View → Larger text / Smaller text / Normal text size*
  (Ctrl +, Ctrl −, Ctrl 0), from 80% to 300%. The size is remembered.

Settings are stored in `~/.config/blighter-restrictor/` (Linux) or
`%APPDATA%\BlighterRestrictor\` (Windows). Each PC keeps its own list of
children and passwords, so on a second parent PC add the children again.

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
  machines & my own family's. It won't catch every problem as everyone's environment
  is a little different.

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
