; KO Ticaret Takip - Windows kurulum betiği (Inno Setup 6)
; Derleme: ISCC.exe /DAppVersion=1.1.0 packaging\installer.iss
; Girdi:   dist\KOTicaretTakip\  (PyInstaller klasör çıktısı)
; Çıktı:   dist\KOTicaretTakip_Kurulum.exe

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "KO Ticaret Takip"
#define AppPublisher "Arvion Digital — MesutCan"
#define AppExe "KOTicaretTakip.exe"

[Setup]
; AppId sabit kalmalı: yeni sürümler eskisinin üzerine kurulur.
AppId={{717010BA-8D52-4056-AC86-8E504689DEA0}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Kurulumu
VersionInfoProductName={#AppName}
; Yönetici izni istemez; kullanıcının kendi klasörüne kurar (%LOCALAPPDATA%\Programs).
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\assets\icon.ico
OutputDir=..\dist
OutputBaseFilename=KOTicaretTakip_Kurulum
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Program açıksa kurulum/kaldırma öncesi kapatılmasını önerir.
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstüne kısayol oluştur"; GroupDescription: "Ek kısayollar:"

[Files]
Source: "..\dist\KOTicaretTakip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Eski sürümden kalan program dosyalarını temizle (kullanıcı verileri ayrı klasörde, etkilenmez).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} Kaldır"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} programını şimdi aç"; Flags: nowait postinstall skipifsilent

[Messages]
turkish.FinishedLabel=Kurulum tamamlandı.%n%nKayıtlarınız AppData\Local\KOTicaretTakip klasöründe saklanır; program kaldırılsa veya güncellense bile silinmez.

; Not: Kullanıcı verileri (%LOCALAPPDATA%\KOTicaretTakip) kaldırma sırasında BİLEREK silinmez.
