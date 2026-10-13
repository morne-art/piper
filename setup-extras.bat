@echo off
title Piper setup (you can keep using Piper)
cd /d "%~dp0"
set OPENJARVIS_NO_UPDATE_CHECK=1
echo Piper is already running. This window finishes the extra downloads, then closes by itself.
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY set PY=py -3
if not exist ".fast-voice-%COMPUTERNAME%" ( %PY% setup_voices.py && echo done> ".fast-voice-%COMPUTERNAME%" )
if not exist ".openjarvis-setup-%COMPUTERNAME%" call install-knowledge.bat auto
if not exist ".companion-setup-%COMPUTERNAME%" call install-companion.bat auto
start "Piper on screen" /min %PY% companion.py
echo All done.
timeout /t 5 >nul
