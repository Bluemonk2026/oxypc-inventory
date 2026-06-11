; =============================================================================
;  OxyPC Inventory Management System
;  FULLY STANDALONE INSTALLER  — No prerequisites required
;  Bundles: Python 3.11 embedded + PostgreSQL 16 + Cloudflare tunnel
;  Version : 1.0-UAT
;
;  HOW TO BUILD:
;    Run build_all.bat  (does prepare_bundle + Inno Setup compile automatically)
;
;  OUTPUT:  dist\OxyPC_UAT_Setup.exe
; =============================================================================

#define AppName      "OxyPC Inventory"
#define AppVersion   "1.0-UAT"
#define AppPublisher "OxyPC"

[Setup]
AppId={{F9C3D2A1-7B4E-4F0C-9E2A-ABCD12345678}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=http://localhost:8000
DefaultDirName=C:\OxyPC
DefaultGroupName=OxyPC Inventory
DisableProgramGroupPage=no
; No special privilege needed since we install to C:\OxyPC not Program Files
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=OxyPC_UAT_Setup
; Maximum compression — exe will be ~200-250 MB
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
WizardResizable=no
; Prevent running twice
AppMutex=OxyPCInstallerMutex
UninstallDisplayName={#AppName} UAT
MinVersion=10.0.17763
; Splash/header text
WizardImageFile=compiler:WizModernImage.bmp
WizardSmallImageFile=compiler:WizModernSmallImage.bmp

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to OxyPC Inventory Setup
WelcomeLabel2=This installer will set up [name/ver] on your computer.%n%nThis is a fully self-contained install — no Python or PostgreSQL required.%n%nAll UAT user accounts are pre-created. See UAT_Credentials_Sheet.txt after install.%n%nClick Next to continue.

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startmenu";   Description: "Create Start Menu group";  GroupDescription: "Shortcuts:"; Flags: checked
Name: "autostart";   Description: "Start OxyPC when Windows starts (recommended for UAT server)"; GroupDescription: "Startup:"; Flags: unchecked

; =============================================================================
;  FILES — bundle\ must exist (created by prepare_bundle.bat)
; =============================================================================
[Files]

; ── Bundled runtimes ──────────────────────────────────────────────────────────
Source: "bundle\python\*";      DestDir: "{app}\python";     Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "bundle\pgsql\*";       DestDir: "{app}\pgsql";      Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "bundle\pgdata\*";      DestDir: "{app}\pgdata";     Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "bundle\cloudflared.exe"; DestDir: "{app}";          Flags: ignoreversion; Components: main

; ── App source code ───────────────────────────────────────────────────────────
Source: "main.py";              DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "launcher.py";          DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "config.py";            DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "database.py";          DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "templates_config.py";  DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "setup_db.py";          DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "upgrade_db.py";        DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "seed_uat_users.py";    DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "setup_uat_input.txt";  DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "requirements.txt";     DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "UAT_Credentials_Sheet.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: main

; ── Bundled config (pre-configured for port 5433) ─────────────────────────────
Source: "bundle\config.ini";    DestDir: "{app}"; Flags: ignoreversion; Components: main

; ── Subfolders ────────────────────────────────────────────────────────────────
Source: "auth\*";              DestDir: "{app}\auth";      Flags: ignoreversion recursesubdirs; Components: main
Source: "models\*";            DestDir: "{app}\models";    Flags: ignoreversion recursesubdirs; Components: main
Source: "routers\*";           DestDir: "{app}\routers";   Flags: ignoreversion recursesubdirs; Components: main
Source: "schemas\*";           DestDir: "{app}\schemas";   Flags: ignoreversion recursesubdirs; Components: main
Source: "templates\*";         DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs; Components: main
Source: "static\*";            DestDir: "{app}\static";    Flags: ignoreversion recursesubdirs; Components: main

[Components]
Name: main; Description: OxyPC Inventory (complete install); Types: full compact custom; Flags: fixed

[Dirs]
Name: "{app}\logs"

; =============================================================================
;  LAUNCHER SCRIPTS
; =============================================================================
[Files]
Source: "oxypc_launcher.bat";  DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "oxypc_stop.bat";      DestDir: "{app}"; Flags: ignoreversion; Components: main

[Icons]
; ── Desktop ──────────────────────────────────────────────────────────────────
Name: "{userdesktop}\OxyPC Inventory";        Filename: "{app}\oxypc_launcher.bat"; IconFilename: "{app}\static\favicon.ico"; Tasks: desktopicon; Comment: "Start OxyPC Inventory Server"
Name: "{userdesktop}\OxyPC — Stop Server";    Filename: "{app}\oxypc_stop.bat";     IconFilename: "{app}\static\favicon.ico"; Tasks: desktopicon

; ── Start Menu ────────────────────────────────────────────────────────────────
Name: "{group}\Start OxyPC Server";           Filename: "{app}\oxypc_launcher.bat"; IconFilename: "{app}\static\favicon.ico"; Tasks: startmenu
Name: "{group}\Stop OxyPC Server";            Filename: "{app}\oxypc_stop.bat";     IconFilename: "{app}\static\favicon.ico"; Tasks: startmenu
Name: "{group}\UAT Credentials";              Filename: "{app}\UAT_Credentials_Sheet.txt";                                    Tasks: startmenu
Name: "{group}\Uninstall OxyPC";              Filename: "{uninstallexe}";                                                     Tasks: startmenu

; ── Windows Startup (optional) ───────────────────────────────────────────────
Name: "{userstartup}\OxyPC Inventory";        Filename: "{app}\oxypc_launcher.bat"; Tasks: autostart

; =============================================================================
;  POST-INSTALL ACTIONS
; =============================================================================
[Run]
; Nothing to compile/install — everything is pre-built in bundle\
; Just offer to launch immediately
Filename: "{app}\oxypc_launcher.bat"; Description: "Launch OxyPC Server now"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

[UninstallRun]
Filename: "{app}\oxypc_stop.bat"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated

; =============================================================================
;  CODE
; =============================================================================
[Code]
function InitializeSetup(): Boolean;
begin
  // Check Windows 10 or later (already enforced by MinVersion but just in case)
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    // Show the credentials file
    MsgBox(
      'OxyPC Inventory has been installed successfully!' + #13#10 + #13#10 +
      'UAT Credentials have been saved to:' + #13#10 +
      '  ' + ExpandConstant('{app}') + '\UAT_Credentials_Sheet.txt' + #13#10 + #13#10 +
      'To start the server:' + #13#10 +
      '  Double-click the "OxyPC Inventory" desktop shortcut.' + #13#10 + #13#10 +
      'The internet URL will appear in the console window.',
      mbInformation, MB_OK
    );
  end;
end;
