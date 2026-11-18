; -----------------------------------------------------------------------------
; Blighter Restrictor - Windows installer definition (Inno Setup 6).
;
; Purpose: package the PyInstaller output folder into one Setup.exe that
; installs for the current user (no administrator rights needed), adds a
; Start-menu shortcut and an optional desktop shortcut, and an uninstaller.
; Settings (%APPDATA%\BlighterRestrictor) and saved passwords (Windows
; Credential Manager) are kept on uninstall.  Third-party notices and licence
; texts are installed next to the program.
; Built by windows\build_windows.ps1, which passes /DAppVersion=<ver>.
;
; Copyright (C) 2026 Ian Packer
; SPDX-License-Identifier: GPL-3.0-or-later
; This program is free software: you can redistribute it and/or modify it
; under the terms of the GNU General Public License as published by the Free
; Software Foundation, either version 3 of the License, or (at your option)
; any later version.  It is distributed WITHOUT ANY WARRANTY; see the
; LICENSE file or <https://www.gnu.org/licenses/> for details.
; -----------------------------------------------------------------------------
#ifndef AppVersion
  #define AppVersion "1.1.1"
#endif

[Setup]
AppId={{6E7B0B1C-3B7E-4C0B-9E55-B1A6E7A0C001}
AppName=Blighter Restrictor
AppVersion={#AppVersion}
AppPublisher=Ian Packer
DefaultDirName={autopf}\Blighter Restrictor
DefaultGroupName=Blighter Restrictor
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=BlighterRestrictor-Setup-{#AppVersion}
SetupIconFile=blighter.ico
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\BlighterRestrictor.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\dist\BlighterRestrictor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Blighter Restrictor"; Filename: "{app}\BlighterRestrictor.exe"
Name: "{group}\Uninstall Blighter Restrictor"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Blighter Restrictor"; Filename: "{app}\BlighterRestrictor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BlighterRestrictor.exe"; Description: "Start Blighter Restrictor"; Flags: nowait postinstall skipifsilent
