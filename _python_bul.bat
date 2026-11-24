@echo off
rem Bilgisayardaki Python'u bulur ve PY degiskenine yazar.
set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY (py -3.13 --version >nul 2>&1 && set "PY=py -3.13")
if not defined PY (py -3 --version >nul 2>&1 && set "PY=py -3")
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (
  echo.
  echo [HATA] Python bulunamadi.
  echo Lutfen https://www.python.org/downloads/ adresinden Python 3.12 kurun.
  echo Kurulumda "Add python.exe to PATH" kutusunu isaretlemeyi unutmayin.
  echo.
  pause
  exit /b 1
)
exit /b 0
