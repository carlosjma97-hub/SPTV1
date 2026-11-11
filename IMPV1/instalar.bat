@echo off
setlocal
title Instalador DocPrinter TI

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

set "ORIGEN=%~dp0dist\DocPrinterTI"
if not exist "%ORIGEN%\DocPrinterTI.exe" (
    set "ORIGEN=%~dp0DocPrinterTI"
)
if not exist "%ORIGEN%\DocPrinterTI.exe" (
    echo.
    echo ERROR: No se encontro la carpeta con los archivos de DocPrinterTI.
    echo Asegurese de que la carpeta 'DocPrinterTI' o 'dist\DocPrinterTI' este junto a este instalador.
    echo.
    pause
    exit /b 1
)

set "DEST=%ProgramFiles%\DocPrinterTI"
echo.
echo [1/3] Copiando archivos a %DEST%...
mkdir "%DEST%" 2>nul
xcopy /E /Y /I /Q "%ORIGEN%\*" "%DEST%\" >nul
if %errorLevel% neq 0 (
    echo ERROR: No se pudieron copiar los archivos.
    pause
    exit /b 1
)

echo [2/3] Configurando permisos de seguridad y tarea del sistema...
"%DEST%\DocPrinterTI.exe" setup install
if %errorLevel% neq 0 (
    echo AVISO: El componente administrativo reporto un codigo de salida no cero.
    echo Revise el registro en C:\ProgramData\DocPrinterTI-instalacion.log
)

echo [3/3] Creando acceso directo en el Escritorio publico...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $d = [Environment]::GetFolderPath('CommonDesktopDirectory'); $s = $ws.CreateShortcut($d + '\DocPrinter TI.lnk'); $s.TargetPath = '%DEST%\DocPrinterTI.exe'; $s.WorkingDirectory = '%DEST%'; $s.Save()"

echo.
echo ====================================================================
echo   INSTALACION COMPLETADA CON EXITO
echo ====================================================================
echo DocPrinter TI quedo instalado en: %DEST%
echo El acceso directo ya esta disponible en el Escritorio.
echo El funcionario podra ejecutarlo sin necesidad de permisos de admin.
echo.
pause
exit /b 0
