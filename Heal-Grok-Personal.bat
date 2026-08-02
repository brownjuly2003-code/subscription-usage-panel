@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem  ONE-TIME fix for GROK/personal (uedomskikh@gmail.com)
rem
rem  Grok Build / work CLI uses  %USERPROFILE%\.grok-work
rem  Personal panel card uses    %USERPROFILE%\.grok
rem
rem  Logging in from the wrong home does NOTHING for personal.
rem  This script forces the personal home only.
rem ============================================================

set "GROK_HOME=%USERPROFILE%\.grok"
set "EXE=%GROK_HOME%\bin\grok.exe"
if not exist "%EXE%" (
  where grok >nul 2>&1
  if errorlevel 1 (
    echo ERROR: grok.exe not found in %GROK_HOME%\bin or PATH
    exit /b 1
  )
  set "EXE=grok"
)

echo.
echo  Personal home: %GROK_HOME%
echo  Expected email: uedomskikh@gmail.com
echo  Work home is DIFFERENT: %USERPROFILE%\.grok-work
echo.

if exist "%GROK_HOME%\auth.json" (
  copy /Y "%GROK_HOME%\auth.json" "%GROK_HOME%\auth.json.bak-before-login" >nul
  echo  Backup: auth.json.bak-before-login
)

echo  Starting official grok login for PERSONAL only...
echo  Complete the browser flow ONCE. Wait for terminal success.
echo.
"%EXE%" login --oauth
set "LOGIN_RC=%ERRORLEVEL%"
echo.
echo  login exit code: %LOGIN_RC%

cd /d "%~dp0"
python -u -c "from pathlib import Path; import time, httpx; from panel.providers import grok as g; h=Path.home()/'.grok'; k,e,x,t,r=g._read_auth(h); print('email', e); print('auth mtime', time.strftime('%%Y-%%m-%%d %%H:%%M:%%S', time.localtime((h/'auth.json').stat().st_mtime))); print('token left min', round((x-time.time())/60,1) if x else None); c=httpx.Client(timeout=20); ok,d=g._refresh_oidc(h,c,15); print('refresh_ok', ok, d); r=g.fetch_grok('grok-personal','GROK/personal',h,c,15); print('panel', r.status.value, [round(w.rem_pct,1) for w in r.windows]); raise SystemExit(0 if ok and r.status.value=='live' else 1)"
if errorlevel 1 (
  echo.
  echo  FAIL: personal still not live. If login looked ok, wrong account was used.
  echo  Restore backup if needed: copy auth.json.bak-before-login auth.json
  pause
  exit /b 1
)
echo.
echo  OK: personal SuperGrok is LIVE and refresh works.
echo  Panel will NOT rewrite this auth.json anymore ^(CLI owns tokens^).
pause
exit /b 0
