@echo off
setlocal
title Desinstalador DocPrinter TI

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ====================================================================
    echo   ERROR: Se requieren privilegios de Administrador.
    echo   Haga clic derecho en este archivo y elija:
    echo   'Ejecutar como administrador'
    echo ====================================================================
    echo.
    pause
    exit /b 1
)

set "DEST=%ProgramFiles%\DocPrinterTI"
if exist "%DEST%\DocPrinterTI.exe" (
    echo [1/2] Retirando tarea administrativa y permisos...
    "%DEST%\DocPrinterTI.exe" setup uninstall --keep-logs
    echo [2/2] Eliminando archivos del programa...
    rd /s /q "%DEST%" 2>nul
)

del /f /q "%PUBLIC%\Desktop\DocPrinter TI.lnk" 2>nul

echo.
echo ====================================================================
echo   DESINSTALACION COMPLETADA
echo ====================================================================
echo Se retiro DocPrinter TI. Los registros en ProgramData se conservaron.
echo.
pause
exit /b 0
