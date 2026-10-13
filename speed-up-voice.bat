@echo off
title Piper - speeding up the voice
cd /d "%~dp0"
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY py -3 --version >nul 2>&1 && set PY=py -3
echo === Making Piper's voice faster (one time only) ===
%PY% -m pip install pyttsx3 >nul 2>&1
echo Trying to run the voice on the graphics card...
%PY% -m pip uninstall -y onnxruntime >nul 2>&1
%PY% -m pip install onnxruntime-directml >nul 2>&1
%PY% -c "import onnxruntime as o,sys; sys.exit(0 if 'DmlExecutionProvider' in o.get_available_providers() else 1)" >nul 2>&1
if errorlevel 1 (
  echo No usable graphics card for the voice. Putting things back as they were...
  %PY% -m pip uninstall -y onnxruntime-directml >nul 2>&1
  %PY% -m pip install onnxruntime >nul 2>&1
) else (
  echo The voice will now use the graphics card.
)
%PY% -c "import kokoro_onnx" >nul 2>&1 || %PY% -m pip install onnxruntime >nul 2>&1
echo done> ".voice-boost-%COMPUTERNAME%"
echo === Done. Piper checks the voice speed every time it starts: see the gear, VOICE. ===
if /i not "%1"=="auto" pause
