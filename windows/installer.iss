; -----------------------------------------------------------------------------
; Blighter Restrictor - Windows installer definition (Inno Setup 6).
;
; Purpose: package the PyInstaller output folder into one Setup.exe that
; installs for the current user (no administrator rights needed), adds a
; Start-menu shortcut and an optional desktop shortcut, and an uninstaller.
; Settings (%APPDATA%\BlighterRestrictor) and saved passwords (Windows
; Credential Manager) are kept on uninstall.
; Built by windows\build_windows.ps1, which passes /DAppVersion=<ver>.
; -----------------------------------------------------------------------------
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6E7B0B1C-3B7E-4C0B-9E55-B1A6E7A0C001}
AppName=Blighter Restrictor
AppVersion={#AppVersion}
AppPublisher=Ways Property
DefaultDirName={autopf}\Blighter Restrictor
DefaultGroupName=Blighter Restrictor
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=BlighterRestrictor-Setup-{#AppVersion}
SetupIconFile=blighter.ico
UninstallDisplayIcon={app}\BlighterRestrictor.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\BlighterRestrictor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Blighter Restrictor"; Filename: "{app}\BlighterRestrictor.exe"
Name: "{group}\Uninstall Blighter Restrictor"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Blighter Restrictor"; Filename: "{app}\BlighterRestrictor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BlighterRestrictor.exe"; Description: "Start Blighter Restrictor"; Flags: nowait postinstall skipifsilent
