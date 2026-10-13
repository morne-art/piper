@echo off
title Piper - phone access
cd /d "%~dp0"
echo.
echo === Use Piper from your phone, at home or away ===
echo.
echo This uses Tailscale: a free, private connection between YOUR devices only.
echo Nothing is opened to the internet, and Piper also asks for a PIN.
echo.
where tailscale >nul 2>&1
if errorlevel 1 (
  echo Step 1: Tailscale isn't installed on this PC yet. Opening the download page...
  echo         Install it, sign in, then run this file again.
  start "" https://tailscale.com/download/windows
  pause & exit /b
)
set /p PIN=Choose a PIN for your phone (at least 6 digits):
set PY=python
python --version >nul 2>&1 || set PY=py -3
%PY% -c "import json,sys;p='config.json';c=json.load(open(p,encoding='utf-8'));c['remote']={'enabled':True,'pin':sys.argv[1]};json.dump(c,open(p,'w',encoding='utf-8'),indent=2)" "%PIN%"
echo.
echo Connecting Piper to your private Tailscale network...
tailscale serve --bg 8790
if errorlevel 1 (
  echo.
  echo Tailscale needs HTTPS turned on once. Opening the setting: switch on "HTTPS Certificates", then run this file again.
  start "" https://login.tailscale.com/admin/dns
  pause & exit /b
)
echo.
echo === Done. Your phone address is the https:// link below ===
tailscale serve status
echo.
echo On your phone:
echo   1. Install Tailscale from the App Store / Play Store and sign in with the SAME account.
echo   2. Open the https:// address above in Safari or Chrome, and enter your PIN.
echo   3. Tap Share / menu, then "Add to Home Screen" to get the Piper icon.
echo.
echo Keep this PC on (and Piper running) for your phone to reach it.
echo To switch phone access off later: run disable-phone.bat
pause
