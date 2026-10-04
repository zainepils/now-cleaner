[Setup]
AppId={{8F963261-081C-4B05-A16A-24C869F813D0}
AppName=NOW Cleaner
AppVersion=0.3.2
AppPublisher=Zaine Pilsworth
AppPublisherURL=https://github.com/zainepils/now-cleaner
DefaultDirName={localappdata}\Programs\NOW Cleaner
DefaultGroupName=NOW Cleaner
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
OutputDir=..\dist\windows-release
OutputBaseFilename=NOW-Cleaner-Windows-Setup
SetupIconFile=..\build\now-cleaner.ico
UninstallDisplayIcon={app}\NOW Cleaner.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "..\dist\NOW Cleaner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NOW Cleaner"; Filename: "{app}\NOW Cleaner.exe"

[Run]
Filename: "{app}\NOW Cleaner.exe"; Description: "Open NOW Cleaner"; Flags: nowait postinstall skipifsilent unchecked
