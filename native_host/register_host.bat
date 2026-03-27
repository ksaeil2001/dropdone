@echo off
chcp 65001 > /dev/null
setlocal

set "HOST_DIR=%~dp0"
if "%HOST_DIR:~-1%"=="\" set "HOST_DIR=%HOST_DIR:~0,-1%"

set "JSON_PATH=%HOST_DIR%\dropdone_host.json"
set "HOST_PY=%HOST_DIR%\dropdone_host.py"
set "LAUNCHER=%HOST_DIR%\dropdone_host_run.bat"
set "HELPER=%HOST_DIR%\register_host_helper.py"
set "REG_KEY=HKCU\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host"

echo.
echo [1/3] Creating launcher: %LAUNCHER%
(echo @echo off) > "%LAUNCHER%"
(echo python "%HOST_PY%") >> "%LAUNCHER%"

echo [2/3] Updating dropdone_host.json ...
python "%HELPER%"
if errorlevel 1 (
  echo [ERROR] Python failed. Make sure Python is in PATH.
  pause & exit /b 1
)

echo [3/3] Writing registry key...
reg add "%REG_KEY%" /ve /t REG_SZ /d "%JSON_PATH%" /f
if errorlevel 1 (
  echo [ERROR] reg add failed.
  pause & exit /b 1
)

echo.
echo ============================================================
echo  Done!
echo  JSON   : %JSON_PATH%
echo  RegKey : %REG_KEY%
echo ============================================================
echo  NEXT: Replace YOUR_EXTENSION_ID in dropdone_host.json
echo        with the actual Chrome extension ID.
echo.
pause
