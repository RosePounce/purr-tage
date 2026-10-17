; Windows installer - compiled by Inno Setup 6 (iscc.exe).
; The version is passed on the command line: iscc /DVersion=1.2.3 installer.iss

#ifndef Version
  #define Version "0.0.0-dev"
#endif
#define Name "Purr-tage : La Guerre des Chats"
; Windows forbids ":" in a file name, and shortcuts such as the Start menu
; group are file names. Hence this variant, without the colon.
#define FileName "Purr-tage - La Guerre des Chats"
#define Exe "Purrtage.exe"

[Setup]
; The AppId does not change with the name: a "La Guerre des Chats"
; installation must update itself, not install a second time.
AppId={{B7F1C3A2-5E4D-4A8B-9C1E-6A2D3F8B4C57}
AppName={#Name}
AppVersion={#Version}
AppPublisher=MmeOokamy
DefaultDirName={autopf}\Purrtage
DefaultGroupName={#FileName}
DisableProgramGroupPage=yes
; "lowest": install into the user folder, without asking for administrator
; rights. The player has nothing to confirm.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=Purrtage-{#Version}-installeur
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\{#Exe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; \
    GroupDescription: "Raccourcis :"

[Files]
Source: "..\..\dist\Purrtage\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#FileName}"; Filename: "{app}\{#Exe}"
Name: "{group}\Désinstaller {#FileName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#FileName}"; Filename: "{app}\{#Exe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Exe}"; Description: "Lancer {#Name}"; \
    Flags: nowait postinstall skipifsilent

[Messages]
french.WelcomeLabel2=Ce programme va installer {#Name} sur votre ordinateur.%n%nLe jeu fonctionne seul : ni Python ni aucune autre installation n'est nécessaire.%n%nPour jouer à deux sur le réseau local, Windows demandera l'autorisation du pare-feu au premier hébergement : acceptez pour les réseaux privés.
