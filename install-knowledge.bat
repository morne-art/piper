@echo off
title Piper - knowledge setup
cd /d "%~dp0"
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY py -3 --version >nul 2>&1 && set PY=py -3
echo === Piper: web knowledge through OpenJarvis (one time only) ===
%PY% setup_openjarvis.py
where ollama >nul 2>&1
if not errorlevel 1 (
  echo Downloading a faster brain for this PC: qwen2.5:7b ^(about 4.7 GB, one time only^)...
  ollama pull qwen2.5:7b && %PY% -c "import json;c=json.load(open('config.json'));c['ollama_model']='qwen2.5:7b';json.dump(c,open('config.json','w'),indent=2);print('Piper will think with qwen2.5:7b. Change it any time in the gear, BRAIN.')"
)
echo done> ".openjarvis-setup-%COMPUTERNAME%"
echo === Done ===
if /i not "%1"=="auto" pause
