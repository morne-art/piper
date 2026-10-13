@echo off
title Piper check
cd /d "%~dp0"
echo Close any black Piper windows first, then press a key.
pause >nul
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY set PY=py -3
%PY% check_piper.py
pause
