@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "EXTENSION_ID=aanekpdighliaaaekihmhnapnbdoiacl"

powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%register_host.ps1" -ExtensionId "%EXTENSION_ID%"
if errorlevel 1 (
  echo [ERROR] Native host registration failed.
  pause
  exit /b 1
)

echo.
echo [OK] Native host registration completed.
pause
