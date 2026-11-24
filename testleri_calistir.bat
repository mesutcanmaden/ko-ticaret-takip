@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Once "1_kurulum.bat" dosyasini calistirin.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pytest -v
pause
