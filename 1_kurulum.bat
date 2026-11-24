@echo off
cd /d "%~dp0"
echo ==================================================
echo  KO Ticaret Takip - KURULUM (yalnizca ilk seferde)
echo ==================================================
call _python_bul.bat || exit /b 1
echo Kullanilan Python: %PY%
if not exist ".venv\Scripts\python.exe" (
  echo Sanal ortam olusturuluyor...
  %PY% -m venv .venv || goto :hata
)
echo Gerekli paketler indiriliyor (internet gerekir, birkac dakika surebilir)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt || goto :hata
echo.
echo Kurulum tamamlandi. Simdi "2_calistir.bat" ile programi acabilir
echo ya da "3_exe_olustur.bat" ile EXE dosyasi olusturabilirsiniz.
pause
exit /b 0
:hata
echo.
echo [HATA] Kurulum tamamlanamadi. Internet baglantinizi kontrol edip tekrar deneyin.
pause
exit /b 1
