@echo off
cd /d "%~dp0"
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY set PY=py -3
echo Setting the voice engine back to the standard one (one time only)...
%PY% -m pip uninstall -y onnxruntime-directml >nul 2>&1
%PY% -m pip install --force-reinstall --no-deps onnxruntime >nul 2>&1
%PY% -m pip install onnxruntime pyttsx3 >nul 2>&1
%PY% -c "import onnxruntime" >nul 2>&1 && echo done> ".voice-repair-%COMPUTERNAME%"
