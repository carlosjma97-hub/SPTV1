Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!define APP "DocPrinter TI"
!define VER "1.0.0"
!define UKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\DocPrinterTI"
!define LOGFILE "C:\ProgramData\DocPrinterTI-instalacion.log"

Name "${APP}"
OutFile "DocPrinterTI_Setup.exe"
InstallDir "$PROGRAMFILES64\DocPrinterTI"
InstallDirRegKey HKLM "Software\DocPrinterTI" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
!define MUI_ICON "icon.ico"
!define MUI_UNICON "icon.ico"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Se requiere Windows de 64 bits."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "Se requiere Windows 10 u 11."
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd

Section "Instalar"
  SetRegView 64
  SetShellVarContext all
  IfFileExists "$INSTDIR\DocPrinterTI.exe" 0 +3
    nsExec::ExecToLog '"$INSTDIR\DocPrinterTI.exe" setup uninstall --keep-logs'
    Pop $0
  SetOutPath "$INSTDIR"
  File /r "..\dist\DocPrinterTI\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  DetailPrint "Configurando componente administrativo..."
  nsExec::ExecToLog '"$INSTDIR\DocPrinterTI.exe" setup install'
  Pop $0
  StrCmp $0 "0" +3
    MessageBox MB_ICONSTOP "No se pudo configurar el componente administrativo (codigo $0).$\r$\nDetalle en: ${LOGFILE}"
    Abort

  CreateShortCut "$DESKTOP\DocPrinter TI.lnk" "$INSTDIR\DocPrinterTI.exe"
  CreateDirectory "$SMPROGRAMS\DocPrinter TI"
  CreateShortCut "$SMPROGRAMS\DocPrinter TI\DocPrinter TI.lnk" "$INSTDIR\DocPrinterTI.exe"
  CreateShortCut "$SMPROGRAMS\DocPrinter TI\Desinstalar DocPrinter TI.lnk" "$INSTDIR\Uninstall.exe"

  WriteRegStr HKLM "Software\DocPrinterTI" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${UKEY}" "DisplayName" "${APP}"
  WriteRegStr HKLM "${UKEY}" "DisplayVersion" "${VER}"
  WriteRegStr HKLM "${UKEY}" "Publisher" "Unidad de Sistemas"
  WriteRegStr HKLM "${UKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UKEY}" "DisplayIcon" "$INSTDIR\DocPrinterTI.exe"
  WriteRegStr HKLM "${UKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKLM "${UKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKLM "${UKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UKEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetRegView 64
  SetShellVarContext all
  StrCpy $1 ""
  IfSilent +3
    MessageBox MB_YESNO|MB_ICONQUESTION "Conservar el registro de operaciones (para Sistemas)?" IDNO +2
    StrCpy $1 "--keep-logs"
  nsExec::ExecToLog '"$INSTDIR\DocPrinterTI.exe" setup uninstall $1'
  Pop $0
  Delete "$DESKTOP\DocPrinter TI.lnk"
  RMDir /r "$SMPROGRAMS\DocPrinter TI"
  DeleteRegKey HKLM "${UKEY}"
  DeleteRegKey HKLM "Software\DocPrinterTI"
  RMDir /r "$INSTDIR"
SectionEnd
