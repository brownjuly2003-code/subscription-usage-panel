@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -u check_grok_both.py
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
