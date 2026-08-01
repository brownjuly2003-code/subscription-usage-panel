@echo off
:: Refresh silently (no flash) then open dashboard.html
cd /d "%~dp0"
if not exist ".cache" mkdir ".cache" >nul 2>&1
wscript //B //Nologo "%~dp0refresh-quiet.vbs"
if errorlevel 1 (
  echo Refresh failed. Is Python installed?
  pause
  exit /b 1
)
start "" "%~dp0dashboard.html"
