@echo off
setlocal
REM Genera dist\DocPrinterTI\ (PyInstaller) y el instalador DocPrinterTI_Setup.exe (NSIS).
REM Requisitos en TU PC de desarrollo: Python 3.10+ y (opcional, para el instalador) NSIS: https://nsis.sourceforge.io
cd /d "%~dp0.."

where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% -m pip install -r requirements-dev.txt || goto :error
%PY% -m pytest -q || goto :error
%PY% -m PyInstaller --noconfirm --clean --windowed --name DocPrinterTI --icon build\icon.ico run.py || goto :error

set "MAKENSIS="
if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set "MAKENSIS=%ProgramFiles(x86)%\NSIS\makensis.exe"
if exist "%ProgramFiles%\NSIS\makensis.exe" set "MAKENSIS=%ProgramFiles%\NSIS\makensis.exe"

if defined MAKENSIS (
  "%MAKENSIS%" build\installer.nsi || goto :error
  echo.
  echo LISTO: build\DocPrinterTI_Setup.exe
) else (
  echo.
  echo LISTO: dist\DocPrinterTI\DocPrinterTI.exe  ^(instale NSIS si desea generar un unico instalador Setup.exe^)
)
exit /b 0
:error
echo ERROR: revise el mensaje anterior.
exit /b 1
