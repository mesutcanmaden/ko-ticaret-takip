@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Once "1_kurulum.bat" dosyasini calistirin.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
