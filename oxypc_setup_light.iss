; =============================================================================
;  OxyPC Inventory — LIGHT Installer (uses existing Python + PostgreSQL)
;  No bundling of Python or PostgreSQL — installs app source only (~10 MB)
;  Version : 1.0-UAT
;  Output  : dist\OxyPC_UAT_Setup.exe
; =============================================================================

#define AppName    "OxyPC Inventory"
#define AppVersion "1.0-UAT"
#define AppVer     "1.0"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=OxyPC
DefaultDirName=C:\OxyPC
DefaultGroupName=OxyPC Inventory
DisableProgramGroupPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=OxyPC_UAT_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
AppMutex=OxyPCInstallerMutex2
UninstallDisplayName={#AppName} UAT
MinVersion=10.0.17763

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to OxyPC Inventory Setup
WelcomeLabel2=This installs the OxyPC Inventory Management System for UAT testing.%n%nRequirements already on this machine:%n  - Python 3.11+  (found automatically)%n  - PostgreSQL     (must be running)%n%nAll 9 UAT test accounts are pre-created in the database.%n%nClick Next to continue.

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcuts";  GroupDescription: "Shortcuts:"; Flags: checked
Name: "startmenu";   Description: "Create Start Menu group";   GroupDescription: "Shortcuts:"; Flags: checked

; =============================================================================
;  FILES
; =============================================================================
[Files]
; ── App source ────────────────────────────────────────────────────────────────
Source: "main.py";              DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "config.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "database.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "templates_config.py";  DestDir: "{app}"; Flags: ignoreversion
Source: "setup_db.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "upgrade_db.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "seed_uat_users.py";    DestDir: "{app}"; Flags: ignoreversion
Source: "setup_uat_input.txt";  DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt";     DestDir: "{app}"; Flags: ignoreversion
Source: "config.ini";           DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "UAT_Credentials_Sheet.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "OxyPC_Installation_UAT_Guide_v1.0.docx"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; ── Launcher scripts ──────────────────────────────────────────────────────────
Source: "oxypc_launcher.bat";   DestDir: "{app}"; Flags: ignoreversion
Source: "oxypc_stop.bat";       DestDir: "{app}"; Flags: ignoreversion

; ── Cloudflared (internet tunnel) ────────────────────────────────────────────
Source: "cloudflared.exe";      DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; ── Subfolders ────────────────────────────────────────────────────────────────
Source: "auth\*";               DestDir: "{app}\auth";      Flags: ignoreversion recursesubdirs
Source: "models\*";             DestDir: "{app}\models";    Flags: ignoreversion recursesubdirs
Source: "routers\*";            DestDir: "{app}\routers";   Flags: ignoreversion recursesubdirs
Source: "schemas\*";            DestDir: "{app}\schemas";   Flags: ignoreversion recursesubdirs
Source: "templates\*";          DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs
Source: "static\*";             DestDir: "{app}\static";    Flags: ignoreversion recursesubdirs

[Dirs]
Name: "{app}\logs"

; =============================================================================
;  SHORTCUTS
; =============================================================================
[Icons]
Name: "{userdesktop}\OxyPC Inventory";       Filename: "{app}\oxypc_launcher.bat"; Comment: "Start OxyPC Server"; Tasks: desktopicon
Name: "{userdesktop}\OxyPC — Stop Server";   Filename: "{app}\oxypc_stop.bat";     Comment: "Stop OxyPC Server";  Tasks: desktopicon
Name: "{group}\Start OxyPC Server";          Filename: "{app}\oxypc_launcher.bat"; Tasks: startmenu
Name: "{group}\Stop OxyPC Server";           Filename: "{app}\oxypc_stop.bat";     Tasks: startmenu
Name: "{group}\UAT Credentials";             Filename: "{app}\UAT_Credentials_Sheet.txt"; Tasks: startmenu
Name: "{group}\UAT Guide (Word)";            Filename: "{app}\OxyPC_Installation_UAT_Guide_v1.0.docx"; Tasks: startmenu
Name: "{group}\Uninstall OxyPC";             Filename: "{uninstallexe}"; Tasks: startmenu

; =============================================================================
;  POST-INSTALL ACTIONS
; =============================================================================
[Run]
; Run DB migrations
Filename: "{code:GetPython}"; Parameters: """{app}\upgrade_db.py"""; WorkingDir: "{app}"; \
  Flags: runhidden waituntilterminated; StatusMsg: "Updating database schema..."

; Seed UAT users
Filename: "{code:GetPython}"; Parameters: """{app}\seed_uat_users.py"""; WorkingDir: "{app}"; \
  Flags: runhidden waituntilterminated; StatusMsg: "Creating UAT user accounts..."

; Offer to launch
Filename: "{app}\oxypc_launcher.bat"; WorkingDir: "{app}"; \
  Description: "Start OxyPC Server now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\oxypc_stop.bat"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated

; =============================================================================
;  CODE — auto-detect Python
; =============================================================================
[Code]
var
  PythonPath: String;

function DetectPython(): String;
var
  Candidates: TArrayOfString;
  i: Integer;
begin
  SetArrayLength(Candidates, 6);
  Candidates[0] := 'C:\Python313\python.exe';
  Candidates[1] := 'C:\Python312\python.exe';
  Candidates[2] := 'C:\Python311\python.exe';
  Candidates[3] := ExpandConstant('{pf}\Python313\python.exe');
  Candidates[4] := ExpandConstant('{pf}\Python312\python.exe');
  Candidates[5] := ExpandConstant('{pf}\Python311\python.exe');
  for i := 0 to GetArrayLength(Candidates)-1 do
    if FileExists(Candidates[i]) then begin
      Result := Candidates[i];
      Exit;
    end;
  // Try PATH
  Result := 'python.exe';
end;

function GetPython(Param: String): String;
begin
  Result := PythonPath;
end;

function InitializeSetup(): Boolean;
begin
  PythonPath := DetectPython();
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    MsgBox(
      'OxyPC Inventory installed successfully!' + #13#10 + #13#10 +
      'Install location:  ' + ExpandConstant('{app}') + #13#10 + #13#10 +
      'To start the server:' + #13#10 +
      '  Double-click "OxyPC Inventory" on your Desktop.' + #13#10 + #13#10 +
      'Share the INTERNET URL shown in the console with UAT testers.' + #13#10 + #13#10 +
      'All login credentials are in:' + #13#10 +
      '  UAT_Credentials_Sheet.txt',
      mbInformation, MB_OK
    );
  end;
end;
