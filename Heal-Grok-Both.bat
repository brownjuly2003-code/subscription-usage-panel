@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo  HEAL BOTH Grok panel profiles
echo  - GROK/personal -^> %%USERPROFILE%%\.grok     (uedomskikh@gmail.com)
echo  - GROK/work     -^> %%USERPROFILE%%\.grok-work (russelllovedirty@juniorr.us)
echo  Only BROKEN homes open login.
echo.

call :heal_one "GROK/personal" "%USERPROFILE%\.grok" "uedomskikh@gmail.com"
call :heal_one "GROK/work" "%USERPROFILE%\.grok-work" "russelllovedirty@juniorr.us"

echo.
echo  FINAL CHECK
python -u check_grok_both.py
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%

:heal_one
set "LABEL=%~1"
set "GHOME=%~2"
set "EXPECT=%~3"
set "EXE=%GHOME%\bin\grok.exe"
if not exist "%EXE%" set "EXE=grok"

echo.
echo  --- %LABEL% ---
echo  home: %GHOME%
echo  account: %EXPECT%

python -u -c "from pathlib import Path; import httpx,sys,os; from panel.providers import grok as g; os.environ.pop('PANEL_GROK_OIDC_REFRESH',None); h=Path(sys.argv[1]);
ok=False
if (h/'auth.json').is_file():
  k,e,x,t,r=g._read_auth(h)
  if k and r:
    with httpx.Client(timeout=15) as c:
      o,d=g._refresh_oidc(h,c,12); res=g.fetch_grok('x','x',h,c,12); ok=bool(o and res.status.value=='live')
print('skip' if ok else 'login'); raise SystemExit(0 if ok else 1)" "%GHOME%"
if !ERRORLEVEL! == 0 (
  echo  already LIVE - skip
  exit /b 0
)

echo  NEED LOGIN for %LABEL%
if exist "%GHOME%\auth.json" copy /Y "%GHOME%\auth.json" "%GHOME%\auth.json.bak-before-login" >nul
set "GROK_HOME=%GHOME%"
echo  Opening official grok login. Sign in as: %EXPECT%
"%EXE%" login --oauth
echo  login exit !ERRORLEVEL!

python -u -c "from pathlib import Path; import httpx,sys; from panel.providers import grok as g; h=Path(sys.argv[1]); exp=sys.argv[2];
k,e,x,t,r=g._read_auth(h); print('email',e); 
ok=False; d='no auth'
if (h/'auth.json').is_file():
  with httpx.Client(timeout=20) as c:
    ok,d=g._refresh_oidc(h,c,15); res=g.fetch_grok('x','x',h,c,15); print('refresh',ok,d); print('panel',res.status.value,[round(w.rem_pct,1) for w in res.windows]); ok=bool(ok and res.status.value=='live')
print('RESULT','OK' if ok else 'FAIL'); raise SystemExit(0 if ok else 1)" "%GHOME%" "%EXPECT%"
if !ERRORLEVEL! == 0 (echo  %LABEL% OK) else (echo  %LABEL% FAIL)
exit /b !ERRORLEVEL!
