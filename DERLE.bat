@echo off
chcp 65001 >nul
title Data Analysis Robot - Derleme
echo.
echo ============================================================
echo   Data Analysis Robot - Windows Derleme
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo   HATA: Python bulunamadi.
  echo   https://python.org adresinden Python 3.11 veya 3.12 kurun.
  echo   Kurulumda "Add Python to PATH" secenegini ISARETLEYIN.
  pause & exit /b 1
)

echo   [1/4] Sanal ortam hazirlaniyor...
if not exist venv ( python -m venv venv )
call venv\Scripts\activate.bat

echo   [2/4] Bagimliliklar kuruluyor (birkac dakika surebilir)...
python -m pip install --upgrade pip -q
pip install -r gereksinimler.txt -q
if errorlevel 1 ( echo   HATA: Bagimliliklar kurulamadi. & pause & exit /b 1 )

echo   [3/4] Onceki derleme temizleniyor...
if exist build ( rmdir /s /q build )
if exist dist  ( rmdir /s /q dist )

echo   [4/4] EXE olusturuluyor (5-15 dakika)...
python -m PyInstaller DataAnalysisRobot.spec --noconfirm
if errorlevel 1 ( echo   HATA: Derleme basarisiz. & pause & exit /b 1 )

echo.
echo ============================================================
echo   TAMAMLANDI
echo   Dosya: dist\DataAnalysisRobot.exe
echo ============================================================
echo.
pause
