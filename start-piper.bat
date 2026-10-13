@echo off
title Piper
cd /d "%~dp0"

rem ---- find Python ----
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
  echo Python isn't installed on this PC yet. Setting it up now...
  call install.bat
  exit /b
)
set OPENJARVIS_NO_UPDATE_CHECK=1

rem ---- settings: create, or add new ones without touching yours ----
%PY% config_merge.py

rem ---- quick one-time steps ----
if not exist ".setup-done-%COMPUTERNAME%" call install.bat auto
if not exist ".voice-repair-%COMPUTERNAME%" call repair-voice.bat

rem ---- big downloads in their own window; Piper starts now ----
set NEED=
if not exist ".fast-voice-%COMPUTERNAME%" set NEED=1
if not exist ".openjarvis-setup-%COMPUTERNAME%" set NEED=1
if not exist ".companion-setup-%COMPUTERNAME%" set NEED=1
if defined NEED start "Piper setup" /min cmd /c setup-extras.bat
if not defined NEED start "Piper on screen" /min %PY% companion.py

rem ---- run Piper; it opens the browser itself once it is ready ----
set TRIES=0
:run
%PY% server.py
set CODE=%errorlevel%
if "%CODE%"=="0" goto end
if "%CODE%"=="2" goto end
set /a TRIES+=1
if %TRIES% GEQ 3 goto giveup
echo.
echo Piper stopped unexpectedly (code %CODE%). Restarting...
timeout /t 3 >nul
goto run
:giveup
echo.
echo Piper keeps stopping. Please send a photo of this window.
:end
pause
