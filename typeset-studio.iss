; Inno Setup script for Typeset Studio.
;
; Turns the PyInstaller onedir output (dist\Typeset Studio\) into a friendly
; Setup.exe with a Start-menu shortcut, an optional desktop shortcut, and an
; uninstaller.
;
; Build order:
;   1. build.bat            -> produces dist\Typeset Studio\
;   2. make-installer.bat   -> runs this script through the Inno Setup compiler
;      (or open this .iss in the Inno Setup IDE and click Build)
;
; Requires Inno Setup 6:  https://jrsoftware.org/isdl.php
;
; Notes
; -----
; * Per-user install (PrivilegesRequired=lowest): installs under the user's
;   local app data, so there is NO admin/UAC prompt. Friendlier for authors.
; * User data (manuscripts, projects, edited presets/covers/fonts) lives in
;   %APPDATA%\Typeset Studio and is intentionally NOT removed on uninstall, so
;   uninstalling never deletes someone's books.

#define AppName "Typeset Studio"
#define AppVersion "1.0.0"
#define AppPublisher "Ashforge Studio"
#define AppExe "Typeset Studio.exe"

[Setup]
; A stable AppId keeps upgrades/uninstall linked across versions — do not change it.
AppId={{9F3B2A17-6C4E-4E8A-9E2D-7A1C5B0D3E42}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=dist_installer
OutputBaseFilename=TypesetStudio-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
; SetupIconFile=app.ico     ; uncomment once an icon exists

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; The entire PyInstaller onedir output.
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Offer to launch the app when the installer finishes.
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
