@echo off
cd /d "%~dp0"
echo ==================================================
echo  KO Ticaret Takip - EXE OLUSTURMA
echo ==================================================
if not exist ".venv\Scripts\python.exe" (
  echo Once "1_kurulum.bat" dosyasini calistirin.
  pause
  exit /b 1
)
echo 1/2 Testler calistiriliyor...
".venv\Scripts\python.exe" -m pytest -q || goto :testhata
:build
echo 2/2 EXE olusturuluyor (birkac dakika surebilir)...
".venv\Scripts\python.exe" packaging\make_version_file.py >nul || goto :hata
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir ^
  --name KOTicaretTakip --icon "assets\icon.ico" --add-data "assets;assets" ^
  --version-file "packaging\version_info.txt" main.py || goto :hata
echo.
echo ==================================================
echo  TAMAM! EXE dosyaniz hazir:
echo  %~dp0dist\KOTicaretTakip\KOTicaretTakip.exe
echo  (KOTicaretTakip klasorunu butun olarak tasiyin.)
echo  Kurulum dosyasi icin Inno Setup ile packaging\installer.iss derlenir.
echo  Verileriniz EXE'den bagimsiz olarak su klasorde saklanir:
echo  %LOCALAPPDATA%\KOTicaretTakip
echo ==================================================
explorer "%~dp0dist"
pause
exit /b 0
:testhata
echo.
echo [UYARI] Testlerden biri basarisiz oldu. Yukaridaki hatayi kaydedin.
choice /c EH /m "Yine de EXE olusturulsun mu? (E=Evet, H=Hayir)"
if errorlevel 2 exit /b 1
goto :build
:hata
echo.
echo [HATA] EXE olusturulamadi.
pause
exit /b 1
