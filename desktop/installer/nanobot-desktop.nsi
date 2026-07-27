; ======================================================================
; nanobot Desktop - Windows Installer (NSIS)
; ======================================================================
;
; Build with:
;   makensis /DOUTPUT_DIR=desktop\output desktop\installer\nanobot-desktop.nsi
;
; ======================================================================

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

; ----------------------------------------------------------------------
; Paths - override on command line with -DASSETS_DIR=..., etc.
; ----------------------------------------------------------------------
!ifndef ASSETS_DIR
  !define ASSETS_DIR "desktop\assets"
!endif
!ifndef BACKEND_DIR
  !define BACKEND_DIR "desktop\backend"
!endif
!ifndef LICENSE_PATH
  !define LICENSE_PATH "LICENSE"
!endif
!ifndef SCRIPTS_DIR
  !define SCRIPTS_DIR "desktop\installer\scripts"
!endif

; ----------------------------------------------------------------------
; Branding
; ----------------------------------------------------------------------
!define PRODUCT_NAME "算小智nanobot Desktop"
!define PRODUCT_PUBLISHER "nanobot"
!define PRODUCT_VERSION "0.3.0-logo"
!define PRODUCT_WEB_SITE "https://github.com/HKUDS/nanobot"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\nanobot-desktop.exe"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "${OUTPUT_DIR}\nanobot-desktop-setup-${PRODUCT_VERSION}.exe"
InstallDir "$PROGRAMFILES64\nanobot Desktop"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

; ----------------------------------------------------------------------
; MUI Settings
; ----------------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON "${ASSETS_DIR}\nanobot.ico"
!define MUI_UNICON "${ASSETS_DIR}\nanobot.ico"

; ----------------------------------------------------------------------
; Pages
; ----------------------------------------------------------------------
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSE_PATH}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"

; ----------------------------------------------------------------------
; Install Section
; ----------------------------------------------------------------------
Section "nanobot Desktop" SecMain
    ; 安装/升级前清 WebView2 缓存，避免显示旧内容。
    ; SetShellVarContext current → $LOCALAPPDATA 指向真实用户（而非提权后的 admin）profile。
    SetShellVarContext current
    DetailPrint "Clearing WebView2 cache..."
    RMDir /r "$LOCALAPPDATA\com.nanobot.desktop\EBWebView"
    ; 兼容旧版 hash 命名的 pake 缓存目录（早期 identifier 未固定时）
    RMDir /r "$LOCALAPPDATA\com.pake.a58fcd1\EBWebView"

    SetOutPath "$INSTDIR"

    ; --- Assets (icons) ---
    SetOutPath "$INSTDIR\assets"
    File "${ASSETS_DIR}\nanobot.ico"
    File "${ASSETS_DIR}\nanobot_icon.png"
    File "${ASSETS_DIR}\nanobot_logo.png"
    File "${ASSETS_DIR}\nanobot_mark.svg"
    SetOutPath "$INSTDIR"

    ; --- Python runtime bundle ---
    ; 重要：先 RMDir 整个 python\ 再解压。否则旧版 dist-info 残留，
    ; importlib.metadata 会同时看到 0.2.2 和 0.3.2 两个版本，返回旧号。
    DetailPrint "Replacing Python runtime + nanobot..."
    RMDir /r "$INSTDIR\python"
    SetOutPath "$INSTDIR\python"
    File /r /x "__pycache__" /x "*.pyc" /x "*.pyo" "${OUTPUT_DIR}\python-bundle\*"
    SetOutPath "$INSTDIR"

    ; --- Backend launcher + web onboarding server ---
    DetailPrint "Installing backend..."
    SetOutPath "$INSTDIR\backend"
    File "${BACKEND_DIR}\__init__.py"
    File "${BACKEND_DIR}\launcher.py"
    File "${BACKEND_DIR}\onboard_server.py"
    File "${BACKEND_DIR}\ports.py"
    SetOutPath "$INSTDIR"

    ; --- Pake/Tauri desktop app (native WebView wrapper) ---
    ; Windows 上 Pake 可能产出 .exe 或 .msi，根据实际文件处理
    DetailPrint "Installing Pake desktop app..."
    ${If} ${FileExists} "${OUTPUT_DIR}\nanobot.exe"
      File "${OUTPUT_DIR}\nanobot.exe"
    ${ElseIf} ${FileExists} "${OUTPUT_DIR}\nanobot.msi"
      File "${OUTPUT_DIR}\nanobot.msi"
    ${Else}
      DetailPrint "ERROR: nanobot.exe/msi not found in ${OUTPUT_DIR}"
      Abort
    ${EndIf}
    SetOutPath "$INSTDIR"

    ; --- Create shortcuts ---
    ; IMPORTANT: target is pythonw.exe (windowless) so NO console ever appears.
    ; The launcher starts the gateway silently, serves the web onboarding, and
    ; opens the single Pake window. First run shows the web setup form.
    CreateDirectory "$SMPROGRAMS\nanobot Desktop"

    CreateShortCut "$DESKTOP\nanobot Desktop.lnk" \
        "$INSTDIR\python\pythonw.exe" \
        '"$INSTDIR\backend\launcher.py"' \
        "$INSTDIR\assets\nanobot.ico" \
        0 SW_SHOWNORMAL

    CreateShortCut "$SMPROGRAMS\nanobot Desktop\nanobot Desktop.lnk" \
        "$INSTDIR\python\pythonw.exe" \
        '"$INSTDIR\backend\launcher.py"' \
        "$INSTDIR\assets\nanobot.ico" \
        0 SW_SHOWNORMAL

    CreateShortCut "$SMPROGRAMS\nanobot Desktop\Uninstall nanobot Desktop.lnk" \
        "$INSTDIR\uninst.exe"

    ; --- Register uninstaller ---
    WriteUninstaller "$INSTDIR\uninst.exe"

    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "UninstallString" "$INSTDIR\uninst.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "DisplayIcon" "$INSTDIR\assets\nanobot.ico"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "URLInfoAbout" "${PRODUCT_WEB_SITE}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "NoModify" "1"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "NoRepair" "1"

    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "EstimatedSize" "$0"

    WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\nanobot.exe"
    WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "Path" "$INSTDIR"

    ; Refresh the shell icon cache so upgraded shortcuts show the new icon
    ; immediately.  Windows keeps the cached icon when a file at the same path
    ; is overwritten; SHCNE_ASSOCCHANGED tells the shell to drop & rebuild it.
    System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, i 0, i 0)'
SectionEnd

; ----------------------------------------------------------------------
; Uninstaller
; ----------------------------------------------------------------------
Section "Uninstall"
    DetailPrint "Stopping running nanobot instances..."
    nsExec::ExecToLog 'taskkill /FI "IMAGENAME eq pythonw.exe" /T 2>nul'
    nsExec::ExecToLog 'taskkill /FI "IMAGENAME eq nanobot.exe" /T 2>nul'

    RMDir /r "$INSTDIR\python"
    RMDir /r "$INSTDIR\backend"
    RMDir /r "$INSTDIR\assets"
    Delete "$INSTDIR\nanobot.exe"
    Delete "$INSTDIR\nanobot.msi"
    Delete "$INSTDIR\uninst.exe"
    RMDir "$INSTDIR"

    Delete "$DESKTOP\nanobot Desktop.lnk"
    RMDir /r "$SMPROGRAMS\nanobot Desktop"

    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
SectionEnd

Function .onInit
    ReadRegStr $0 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\nanobot-desktop" \
        "UninstallString"
    ${If} $0 != ""
        MessageBox MB_OKCANCEL|MB_ICONQUESTION \
            "${PRODUCT_NAME} is already installed. Click OK to upgrade (user data preserved) or Cancel." \
            IDOK upgrade
        Abort
        upgrade:
    ${EndIf}
FunctionEnd
