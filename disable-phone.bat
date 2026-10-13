@echo off
cd /d "%~dp0"
tailscale serve --https=443 off >nul 2>&1
tailscale serve reset >nul 2>&1
set PY=python
python --version >nul 2>&1 || set PY=py -3
%PY% -c "import json;p='config.json';c=json.load(open(p,encoding='utf-8'));c['remote']={'enabled':False};json.dump(c,open(p,'w',encoding='utf-8'),indent=2)"
echo Phone access is now OFF. Piper works on this PC only.
pause
