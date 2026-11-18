; -----------------------------------------------------------------------------
; Blighter Restrictor - Windows CHILD laptop installer (Inno Setup 6.3+).
;
; Purpose: one BlighterChild-Setup-<ver>.exe that sets up a child's Windows
; 10/11 laptop with no console window.  It asks every question on normal
; installer pages first (child's account, the "blighter" administrator
; password, the home network, and - only if Squid was installed by something
; else - whether to replace Squid), then runs blighter-setup.ps1 -Gui hidden
; and shows its progress (step n of 9) on an installer page.  If setup fails
; it shows the reason and offers to undo.  The Finished page shows what to
; type into the parent app.  Removal is through Settings > Apps (runs
; blighter-setup.ps1 -Remove -Yes).  Pause / Resume filtering are in the
; Start menu (administrator only).
; The child package (helper, scripts, embedded Python) is carried inside as
; blighter-child-package.zip and unpacked to a temporary folder; the setup
; script copies it to C:\ProgramData\BlighterChild.  Squid is downloaded by
; the setup script (signature and SHA-256 checked there).
; Silent use (tests / technical users):
;   BlighterChild-Setup-<ver>.exe /VERYSILENT /SUPPRESSMSGBOXES /CHILD=<user>
;       [/KEEPPASSWORD] [/NOPRIVATE] [/REPLACESQUID]
;   with the password in the BLIGHTER_ADMIN_PASSWORD environment variable.
; Built by the GitHub workflow:  ISCC /DAppVersion=<ver> windows\child-installer.iss
; (dist\blighter-child-package.zip must exist).
;
; Copyright (C) 2026 Ways Property
; SPDX-License-Identifier: GPL-3.0-or-later
; This program is free software: you can redistribute it and/or modify it
; under the terms of the GNU General Public License as published by the Free
; Software Foundation, either version 3 of the License, or (at your option)
; any later version.  It is distributed WITHOUT ANY WARRANTY; see the
; LICENSE file or <https://www.gnu.org/licenses/> for details.
; -----------------------------------------------------------------------------
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define PkgDir "blighter-child-windows-" + AppVersion

[Setup]
AppId={{3C7A9E52-6B1D-4F0E-9A47-B1A6E7A0C002}
AppName=Blighter Child
AppVersion={#AppVersion}
AppVerName=Blighter Child {#AppVersion}
AppPublisher=Ways Property
AppPublisherURL=https://github.com/ianp5uk/blighter-restrictor
AppSupportURL=https://github.com/ianp5uk/blighter-restrictor/issues
DefaultDirName={commonpf64}\Blighter Child
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyMemo=no
PrivilegesRequired=admin
OutputDir=..\dist
OutputBaseFilename=BlighterChild-Setup-{#AppVersion}
SetupIconFile=blighter.ico
LicenseFile=..\LICENSE
UninstallDisplayName=Blighter Child (web filter for this laptop)
UninstallDisplayIcon={app}\blighter.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=no
SetupLogging=yes

[Messages]
WelcomeLabel2=This sets up Blighter Restrictor on your child's laptop, so you can control and see their web use from the Blighter Restrictor app on your own PC.%n%nRun it on the child's laptop, signed in as a parent (administrator) account. It takes about 5-15 minutes and needs the internet. Keep the laptop plugged in and on your home Wi-Fi.
FinishedHeadingLabel=Blighter is set up on this laptop

[Files]
Source: "..\dist\blighter-child-package.zip"; Flags: dontcopy
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "blighter.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{commonprograms}\Blighter Child\Pause filtering (parent)"; Filename: "{commonappdata}\BlighterChild\Pause Blighter Child.cmd"; IconFilename: "{app}\blighter.ico"
Name: "{commonprograms}\Blighter Child\Resume filtering (parent)"; Filename: "{commonappdata}\BlighterChild\Resume Blighter Child.cmd"; IconFilename: "{app}\blighter.ico"

[Code]
const
  Tag = '##BLIGHTER ';

var
  PkgReady: Boolean;
  ScriptPath: String;
  AccNames, AccFull: TArrayOfString;
  AccAdmin: array of Boolean;
  AdminExists: Boolean;
  SquidOwner: String;
  PublicNets: String;
  Incomplete: Boolean;

  AccountPage, PasswordPage, NetworkPage, SquidPage: TWizardPage;
  AccountCombo: TNewComboBox;
  AdminWarn: TNewStaticText;
  AdminAck: TNewCheckBox;
  KeepPw: TNewCheckBox;
  Pw1, Pw2: TPasswordEdit;
  PwLabel1, PwLabel2: TNewStaticText;
  MarkPrivate: TNewCheckBox;
  ReplaceRadio, CancelRadio: TNewRadioButton;

  Progress: TOutputProgressWizardPage;
  LastError, ResultIp, ResultChild, Notes, LogFile: String;
  FailedUndo, FailedRerun, SquidUpdated, SetupOk: Boolean;
  StepNo: Integer;

function SetEnvironmentVariable(lpName: String; lpValue: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

function PsExe: String;
begin
  Result := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
end;

procedure AppendLog(const S: String);
begin
  if LogFile <> '' then
    SaveStringToFile(LogFile, S + #13#10, True);
  Log(S);
end;

function StartsWith(const S, Prefix: String): Boolean;
begin
  Result := Copy(S, 1, Length(Prefix)) = Prefix;
end;

{ Unpack the child package to the temporary folder (once).  Uses Windows'
  own tar.exe (Windows 10 1803 and later); PowerShell's Expand-Archive is the
  fallback.  Any output goes to the setup log. }
function EnsurePackage: Boolean;
var
  Code: Integer;
  Zip, Dest: String;
begin
  if not PkgReady then begin
    ExtractTemporaryFile('blighter-child-package.zip');
    Zip := ExpandConstant('{tmp}\blighter-child-package.zip');
    Dest := ExpandConstant('{tmp}\pkg');
    ForceDirectories(Dest);
    ScriptPath := Dest + '\{#PkgDir}\blighter-setup.ps1';
    if FileExists(ExpandConstant('{sys}\tar.exe')) then begin
      ExecAndLogOutput(ExpandConstant('{sys}\tar.exe'), '-xf "' + Zip + '" -C "' + Dest + '"',
                       '', SW_HIDE, ewWaitUntilTerminated, Code, nil);
      AppendLog('Unpack with tar.exe: exit code ' + IntToStr(Code));
    end;
    if not FileExists(ScriptPath) then begin
      ExecAndLogOutput(PsExe, '-NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ''' +
           Zip + ''' -DestinationPath ''' + Dest + ''' -Force"', '', SW_HIDE, ewWaitUntilTerminated, Code, nil);
      AppendLog('Unpack with Expand-Archive: exit code ' + IntToStr(Code));
    end;
    PkgReady := FileExists(ScriptPath);
    if not PkgReady then AppendLog('Not found after unpacking: ' + ScriptPath);
  end;
  Result := PkgReady;
end;

function ScriptArgs(const Extra: String): String;
begin
  Result := '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '" ' + Extra;
end;

{ Ask the setup script for the laptop's accounts, Squid owner, networks. }
procedure QueryLaptop;
var
  Output: TExecOutput;
  Code, I, N, P: Integer;
  Line, Kind, Rest: String;
  Parts: TArrayOfString;
begin
  SetArrayLength(AccNames, 0); SetArrayLength(AccFull, 0); SetArrayLength(AccAdmin, 0);
  SquidOwner := 'none'; PublicNets := ''; AdminExists := False; Incomplete := False;
  if not ExecAndCaptureOutput(PsExe, ScriptArgs('-Query'), '', SW_HIDE, ewWaitUntilTerminated, Code, Output) then
    Exit;
  for I := 0 to GetArrayLength(Output.StdOut) - 1 do begin
    Line := Output.StdOut[I];
    P := Pos(#9, Line);
    if P = 0 then Continue;
    Kind := Copy(Line, 1, P - 1);
    Rest := Copy(Line, P + 1, Length(Line));
    if Kind = 'account' then begin
      Parts := StringSplit(Rest, [#9], stAll);
      if GetArrayLength(Parts) >= 3 then begin
        N := GetArrayLength(AccNames);
        SetArrayLength(AccNames, N + 1); SetArrayLength(AccFull, N + 1); SetArrayLength(AccAdmin, N + 1);
        AccNames[N] := Parts[0]; AccFull[N] := Parts[1]; AccAdmin[N] := Parts[2] = '1';
      end;
    end
    else if Kind = 'adminexists' then AdminExists := Rest = '1'
    else if Kind = 'squid' then SquidOwner := Trim(Rest)
    else if Kind = 'incomplete' then Incomplete := Rest = '1'
    else if Kind = 'network' then begin
      if PublicNets <> '' then PublicNets := PublicNets + ', ';
      PublicNets := PublicNets + Rest;
    end;
  end;
end;

{ Run the setup script hidden; its lines drive the progress page. }
procedure OnScriptLine(const S: String; const Error, FirstLine: Boolean);
var
  L, R: String;
  P: Integer;
begin
  AppendLog(S);
  L := Trim(S);
  if StartsWith(L, Tag) then begin
    R := Copy(L, Length(Tag) + 1, Length(L));
    if StartsWith(R, 'step ') then begin
      R := Copy(R, 6, Length(R));
      P := Pos(' ', R);
      StepNo := StrToIntDef(Copy(R, 1, P - 1), StepNo);
      if Progress <> nil then begin
        Progress.SetText(Format('Step %d of 9: %s', [StepNo, Copy(R, P + 1, Length(R))]), '');
        Progress.SetProgress(StepNo - 1, 9);
      end;
    end
    else if StartsWith(R, 'note ') then Notes := Notes + '- ' + Copy(R, 6, Length(R)) + #13#10
    else if StartsWith(R, 'result ip=') then ResultIp := Copy(R, 11, Length(R))
    else if StartsWith(R, 'result child=') then ResultChild := Copy(R, 14, Length(R))
    else if R = 'squid-updated' then SquidUpdated := True
    else if StartsWith(R, 'failed undo=') then begin
      FailedUndo := Copy(R, 13, 1) = '1';
      FailedRerun := Pos('rerun=1', R) > 0;
    end
    else if R = 'done' then SetupOk := True;
  end
  else if StartsWith(L, 'ERROR: ') then
    LastError := Copy(L, 8, Length(L))
  else if (Progress <> nil) and (L <> '') then
    Progress.SetText(Progress.Msg1Label.Caption, L);
end;

function RunScript(const Args, Title: String): Integer;
var
  Code: Integer;
begin
  if (Progress <> nil) and not WizardSilent then begin
    Progress.SetText(Title, '');
    Progress.SetProgress(0, 9);
    Progress.Show;
  end;
  try
    if not ExecAndLogOutput(PsExe, ScriptArgs(Args), '', SW_HIDE, ewWaitUntilTerminated, Code, @OnScriptLine) then
      Code := -1;
  finally
    if (Progress <> nil) and not WizardSilent then Progress.Hide;
  end;
  Result := Code;
end;

{ ---------------------------------------------------------------- start --- }
function InitializeSetup: Boolean;
var
  R: Integer;
begin
  Result := True;
  LogFile := ExpandConstant('{%TEMP}\Blighter-Child-Setup.log');
  SaveStringToFile(LogFile, 'Blighter Child {#AppVersion} setup' + #13#10, False);
  if not EnsurePackage then begin
    SuppressibleMsgBox('Setup could not unpack its files.  Please download the installer again.', mbCriticalError, MB_OK, IDOK);
    Result := False;
    Exit;
  end;
  QueryLaptop;
  if Incomplete then begin
    R := SuppressibleMsgBox('An earlier Blighter setup on this laptop did not finish.' + #13#10#13#10 +
      'Yes - carry on and finish it (recommended)' + #13#10 +
      'No - undo what it did and remove Blighter' + #13#10 +
      'Cancel - leave it for now', mbConfirmation, MB_YESNOCANCEL, IDYES);
    if R = IDNO then begin
      RunScript('-Remove -Yes', 'Removing Blighter...');
      SuppressibleMsgBox('Blighter has been removed.  You can run this installer again later.', mbInformation, MB_OK, IDOK);
      Result := False;
    end
    else if R = IDCANCEL then
      Result := False;
  end;
end;

procedure AccountChanged(Sender: TObject);
var
  I: Integer;
  IsAdmin: Boolean;
begin
  I := AccountCombo.ItemIndex;
  IsAdmin := (I >= 0) and (I < GetArrayLength(AccAdmin)) and AccAdmin[I];
  AdminWarn.Visible := IsAdmin;
  AdminAck.Visible := IsAdmin;
  if not IsAdmin then AdminAck.Checked := False;
end;

procedure KeepPwChanged(Sender: TObject);
begin
  Pw1.Enabled := not KeepPw.Checked;
  Pw2.Enabled := not KeepPw.Checked;
  PwLabel1.Enabled := Pw1.Enabled;
  PwLabel2.Enabled := Pw1.Enabled;
end;

function AddLabel(Page: TWizardPage; const Text: String; Top: Integer): TNewStaticText;
begin
  Result := TNewStaticText.Create(Page);
  Result.Parent := Page.Surface;
  Result.AutoSize := False;
  Result.WordWrap := True;
  Result.Width := Page.SurfaceWidth;
  Result.Top := Top;
  Result.Caption := Text;
  Result.AdjustHeight;
end;

procedure InitializeWizard;
var
  I: Integer;
  T: TNewStaticText;
  Y: Integer;
begin
  { Child's account }
  AccountPage := CreateCustomPage(wpLicense, 'The child''s account',
    'Which Windows account does your child sign in with?');
  T := AddLabel(AccountPage, 'Choose the account your child uses on this laptop.  Blighter filters the web for the whole laptop; this account is used for the warnings below and in the parent app.', 0);
  AccountCombo := TNewComboBox.Create(AccountPage);
  AccountCombo.Parent := AccountPage.Surface;
  AccountCombo.Style := csDropDownList;
  AccountCombo.Top := T.Top + T.Height + ScaleY(10);
  AccountCombo.Width := AccountPage.SurfaceWidth;
  for I := 0 to GetArrayLength(AccNames) - 1 do begin
    if (AccFull[I] <> '') and (AccFull[I] <> AccNames[I]) then
      AccountCombo.Items.Add(AccNames[I] + '  (' + AccFull[I] + ')')
    else
      AccountCombo.Items.Add(AccNames[I]);
  end;
  AccountCombo.OnChange := @AccountChanged;
  AdminWarn := AddLabel(AccountPage, 'This account is an ADMINISTRATOR on this laptop.  An administrator can switch Blighter off.  Blighter will still filter, but it cannot stop an administrator who goes looking.' + #13#10#13#10 +
    'To fix it: keep your own (parent) administrator account, then in Settings > Accounts > Other users, change the child''s account to "Standard user".',
    AccountCombo.Top + AccountCombo.Height + ScaleY(12));
  AdminWarn.Font.Color := clRed;
  AdminAck := TNewCheckBox.Create(AccountPage);
  AdminAck.Parent := AccountPage.Surface;
  AdminAck.Top := AdminWarn.Top + AdminWarn.Height + ScaleY(8);
  AdminAck.Width := AccountPage.SurfaceWidth;
  AdminAck.Caption := 'I understand the child could switch filtering off';
  AdminWarn.Visible := False;
  AdminAck.Visible := False;

  { Administrator password }
  PasswordPage := CreateCustomPage(AccountPage.ID, 'Password for the parent app',
    'Blighter adds a hidden administrator account called "blighter".');
  T := AddLabel(PasswordPage, 'The Blighter Restrictor app on your PC signs in to this laptop with the "blighter" account and this password.  Use at least 10 characters, and write it down - you will type it into the parent app.', 0);
  Y := T.Top + T.Height + ScaleY(10);
  KeepPw := TNewCheckBox.Create(PasswordPage);
  KeepPw.Parent := PasswordPage.Surface;
  KeepPw.Top := Y;
  KeepPw.Width := PasswordPage.SurfaceWidth;
  KeepPw.Caption := 'The "blighter" account already exists - keep its current password';
  KeepPw.Visible := AdminExists;
  KeepPw.Checked := AdminExists;
  KeepPw.OnClick := @KeepPwChanged;
  if AdminExists then Y := Y + KeepPw.Height + ScaleY(10);
  PwLabel1 := AddLabel(PasswordPage, 'Password:', Y);
  Pw1 := TPasswordEdit.Create(PasswordPage);
  Pw1.Parent := PasswordPage.Surface;
  Pw1.Top := PwLabel1.Top + PwLabel1.Height + ScaleY(3);
  Pw1.Width := PasswordPage.SurfaceWidth div 2;
  PwLabel2 := AddLabel(PasswordPage, 'Type it again:', Pw1.Top + Pw1.Height + ScaleY(8));
  Pw2 := TPasswordEdit.Create(PasswordPage);
  Pw2.Parent := PasswordPage.Surface;
  Pw2.Top := PwLabel2.Top + PwLabel2.Height + ScaleY(3);
  Pw2.Width := Pw1.Width;
  KeepPwChanged(nil);

  { Home network }
  NetworkPage := CreateCustomPage(PasswordPage.ID, 'Home network',
    'The parent app can only reach this laptop on a network Windows calls "Private".');
  T := AddLabel(NetworkPage, 'Windows calls this network "Public": ' + PublicNets + #13#10#13#10 +
    'If this is your home network, Blighter will mark it "Private" so the parent app can connect.  (Removing Blighter sets it back.)', 0);
  MarkPrivate := TNewCheckBox.Create(NetworkPage);
  MarkPrivate.Parent := NetworkPage.Surface;
  MarkPrivate.Top := T.Top + T.Height + ScaleY(10);
  MarkPrivate.Width := NetworkPage.SurfaceWidth;
  MarkPrivate.Caption := 'This is my home network - mark it Private';
  MarkPrivate.Checked := True;

  { Existing Squid (only when another program installed it) }
  SquidPage := CreateCustomPage(NetworkPage.ID, 'Squid is already installed',
    'Squid (web filter software) is already on this laptop.');
  T := AddLabel(SquidPage, 'Squid is already installed on this laptop, but it wasn''t installed by Blighter.  Something else may be using it.' + #13#10#13#10 +
    'Blighter needs to replace it with the version it was tested with.  Squid''s current settings will be saved to C:\ProgramData\BlighterChild\backup\squid-before-blighter\ first.', 0);
  ReplaceRadio := TNewRadioButton.Create(SquidPage);
  ReplaceRadio.Parent := SquidPage.Surface;
  ReplaceRadio.Top := T.Top + T.Height + ScaleY(12);
  ReplaceRadio.Width := SquidPage.SurfaceWidth;
  ReplaceRadio.Caption := 'Replace Squid';
  CancelRadio := TNewRadioButton.Create(SquidPage);
  CancelRadio.Parent := SquidPage.Surface;
  CancelRadio.Top := ReplaceRadio.Top + ReplaceRadio.Height + ScaleY(6);
  CancelRadio.Width := SquidPage.SurfaceWidth;
  CancelRadio.Caption := 'Cancel setup (nothing will be changed)';
  CancelRadio.Checked := True;

  Progress := CreateOutputProgressPage('Setting up Blighter',
    'This takes about 5-15 minutes.  Please keep the laptop plugged in and on the home Wi-Fi.');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = NetworkPage.ID then Result := PublicNets = '';
  if PageID = SquidPage.ID then Result := SquidOwner <> 'other';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  { Silent installs take their answers from the command line (and the
    BLIGHTER_ADMIN_PASSWORD variable); the page checks would show message
    boxes nobody can see. }
  if WizardSilent then Exit;
  if CurPageID = AccountPage.ID then begin
    if AccountCombo.ItemIndex < 0 then begin
      MsgBox('Please choose the child''s account.', mbError, MB_OK); Result := False;
    end
    else if AdminAck.Visible and not AdminAck.Checked then begin
      MsgBox('Please tick "I understand" to carry on with an administrator account, or make the account a standard user first.', mbError, MB_OK); Result := False;
    end;
  end
  else if CurPageID = PasswordPage.ID then begin
    if not (KeepPw.Visible and KeepPw.Checked) then begin
      if Length(Pw1.Text) < 10 then begin
        MsgBox('Please use at least 10 characters - this account has full control of the laptop.', mbError, MB_OK); Result := False;
      end
      else if Pw1.Text <> Pw2.Text then begin
        MsgBox('The two passwords do not match.', mbError, MB_OK); Result := False;
      end
      else if Pos('blighter', Lowercase(Pw1.Text)) > 0 then begin
        MsgBox('Windows does not allow the password to contain the word "blighter".', mbError, MB_OK); Result := False;
      end;
    end;
  end
  else if CurPageID = SquidPage.ID then begin
    if not ReplaceRadio.Checked then begin
      MsgBox('Setup will now close.  Nothing has been changed.', mbInformation, MB_OK);
      WizardForm.Close;
      Result := False;
    end;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if (CurPageID = SquidPage.ID) and CancelRadio.Checked then Confirm := False;
end;

function ChosenChild: String;
begin
  if WizardSilent then
    Result := ExpandConstant('{param:CHILD|}')
  else
    Result := AccNames[AccountCombo.ItemIndex];
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := 'Child''s account:' + NewLine + Space + ChosenChild + NewLine + NewLine +
    'Parent app login:' + NewLine + Space + 'blighter';
  if KeepPw.Visible and KeepPw.Checked then Result := Result + ' (current password kept)';
  Result := Result + NewLine + NewLine;
  if PublicNets <> '' then begin
    if MarkPrivate.Checked then
      Result := Result + 'Home network:' + NewLine + Space + 'mark "' + PublicNets + '" Private' + NewLine + NewLine
    else
      Result := Result + 'Home network:' + NewLine + Space + 'leave as Public' + NewLine + NewLine;
  end;
  if SquidOwner = 'other' then
    Result := Result + 'Squid:' + NewLine + Space + 'replace the existing Squid (its settings saved first)' + NewLine + NewLine;
  Result := Result + 'Setup first creates a Windows restore point ("Before Blighter Restrictor") and records the laptop''s current settings, so Blighter can be removed cleanly later.';
end;

{ ------------------------------------------------------------- run setup --- }
function WizardSilentParam(const Name: String): Boolean;
begin
  Result := Pos('/' + Uppercase(Name), Uppercase(GetCmdTail)) > 0;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Args, Pw: String;
  Code, R: Integer;
begin
  Result := '';
  Args := '-Gui -Child "' + ChosenChild + '"';
  if WizardSilent then begin
    if ExpandConstant('{param:CHILD|}') = '' then begin Result := 'No /CHILD= account was given.'; Exit; end;
    if WizardSilentParam('KEEPPASSWORD') then Args := Args + ' -KeepPassword';
    if WizardSilentParam('NOPRIVATE') then Args := Args + ' -NoMarkPrivate';
    if WizardSilentParam('REPLACESQUID') then Args := Args + ' -ReplaceSquid';
  end else begin
    if KeepPw.Visible and KeepPw.Checked then
      Args := Args + ' -KeepPassword'
    else begin
      Pw := Pw1.Text;
      SetEnvironmentVariable('BLIGHTER_ADMIN_PASSWORD', Pw);
    end;
    if (PublicNets <> '') and not MarkPrivate.Checked then Args := Args + ' -NoMarkPrivate';
    if (SquidOwner = 'other') and ReplaceRadio.Checked then Args := Args + ' -ReplaceSquid';
  end;
  Code := RunScript(Args, 'Starting...');
  if not WizardSilent then SetEnvironmentVariable('BLIGHTER_ADMIN_PASSWORD', '');
  if (Code = 0) and SetupOk then Exit;

  if LastError = '' then LastError := 'Setup stopped unexpectedly (code ' + IntToStr(Code) + ').';
  if FailedUndo and FailedRerun then begin
    { Blighter was already working before this run: keeping it is the safe
      default (undoing would remove the filtering completely). }
    R := SuppressibleMsgBox('Setup did not finish:' + #13#10#13#10 + LastError + #13#10#13#10 +
      'Blighter was already installed on this laptop.  Keep it and run this installer again later?  (Recommended.)' + #13#10#13#10 +
      'Yes - keep Blighter as it is' + #13#10 + 'No - remove Blighter completely',
      mbError, MB_YESNO, IDYES);
    if R = IDNO then begin
      RunScript('-Remove -Yes', 'Removing Blighter...');
      Result := LastError + #13#10#13#10 + 'Blighter has been removed.  The full log is in ' + LogFile;
    end else
      Result := LastError + #13#10#13#10 + 'Blighter was left in place - run this installer again to finish.  The full log is in ' + LogFile;
  end
  else if FailedUndo then begin
    R := SuppressibleMsgBox('Setup did not finish:' + #13#10#13#10 + LastError + #13#10#13#10 +
      'Undo the changes made so far?  (Recommended.  This removes Blighter completely and puts the laptop back as it was.)',
      mbError, MB_YESNO, IDYES);
    if R = IDYES then begin
      RunScript('-Remove -Yes', 'Undoing the changes...');
      Result := LastError + #13#10#13#10 + 'The changes have been undone.  The full log is in ' + LogFile;
    end else
      Result := LastError + #13#10#13#10 + 'The changes were left in place - run this installer again to finish.  The full log is in ' + LogFile;
  end else
    Result := LastError + #13#10#13#10 + 'Nothing on the laptop was changed.  The full log is in ' + LogFile;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  S: String;
begin
  if CurPageID = wpFinished then begin
    S := 'Now, on your own PC, open the Blighter Restrictor app and add this laptop with:' + #13#10#13#10 +
      '    Laptop IP address:  ' + ResultIp + #13#10 +
      '    Child''s username:  ' + ResultChild + #13#10 +
      '    Admin login:  blighter  (and the password you chose)' + #13#10#13#10 +
      'Tip: reserve this IP address for the laptop in your router so it does not change.' + #13#10 +
      'The child should sign out and back in once.';
    if Notes <> '' then S := S + #13#10#13#10 + 'Please note:' + #13#10 + Notes;
    if SquidUpdated then
      S := S + #13#10 + 'Setup finished. Note: Squid, the web filter Blighter uses, has been updated by its maintainer since this version of Blighter was tested. Filtering should work normally. If you notice any problems, please email ianp5@pm.me.';
    WizardForm.FinishedLabel.Caption := S;
    WizardForm.FinishedLabel.AdjustHeight;
  end;
end;

{ ---------------------------------------------------------------- removal --- }
procedure OnRemoveLine(const S: String; const Error, FirstLine: Boolean);
var
  L: String;
begin
  Log(S);
  L := Trim(S);
  if StartsWith(L, '==> ') then begin
    UninstallProgressForm.StatusLabel.Caption := 'Removing: ' + Copy(L, 5, Length(L));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
  Script: String;
begin
  if CurUninstallStep = usUninstall then begin
    Script := ExpandConstant('{commonappdata}\BlighterChild\blighter-setup.ps1');
    if FileExists(Script) then begin
      UninstallProgressForm.StatusLabel.Caption := 'Removing Blighter - this can take a few minutes...';
      ExecAndLogOutput(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
        '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" -Remove -Yes', '',
        SW_HIDE, ewWaitUntilTerminated, Code, @OnRemoveLine);
    end;
  end;
end;
