; Instalador de Windows (Inno Setup 6). La CI lo compila con:
;   iscc /DVersion=0.1.0 /DVersionNum=0.1.0 empaquetado\windows\instalador.iss
; Se instala para el usuario actual, sin pedir permisos de administrador.

#ifndef Version
  #define Version "0.1.0"
#endif
; Solo números (x.y.z) para las propiedades del .exe
#ifndef VersionNum
  #define VersionNum "0.1.0"
#endif

[Setup]
AppId={{6B1E5C0A-4F7D-4E3B-9C55-2D7A0E5F3A11}
AppName=estruc-mx
AppVersion={#Version}
VersionInfoVersion={#VersionNum}
AppPublisher=estruc-mx
DefaultDirName={localappdata}\Programs\estruc-mx
DefaultGroupName=estruc-mx
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\instaladores
OutputBaseFilename=estruc-mx-{#Version}-windows-x64-instalador
SetupIconFile=estruc-mx.ico
UninstallDisplayIcon={app}\estruc-mx.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear acceso directo en el escritorio"; Flags: unchecked
Name: "path"; Description: "Añadir estruc-mx-cli al PATH del usuario (línea de comandos)"; Flags: unchecked

[Files]
Source: "..\..\dist\estruc-mx\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Licencia y avisos de terceros a la vista en la carpeta de instalación
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\..\AVISOS_TERCEROS.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\estruc-mx"; Filename: "{app}\estruc-mx.exe"
Name: "{group}\Desinstalar estruc-mx"; Filename: "{uninstallexe}"
Name: "{userdesktop}\estruc-mx"; Filename: "{app}\estruc-mx.exe"; Tasks: escritorio

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Tasks: path; Check: NoEstaEnPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\estruc-mx.exe"; Description: "Abrir estruc-mx"; Flags: nowait postinstall skipifsilent

[Code]
function NoEstaEnPath(Carpeta: string): Boolean;
var
  Actual: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Actual) then
    Result := True
  else
    Result := Pos(';' + Uppercase(Carpeta) + ';', ';' + Uppercase(Actual) + ';') = 0;
end;
