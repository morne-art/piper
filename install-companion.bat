@echo off
title Piper on screen - setup
cd /d "%~dp0"
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY py -3 --version >nul 2>&1 && set PY=py -3
echo === Piper on screen: hold Ctrl+Alt anywhere and ask about what you see ===
echo Installing the screen, microphone and speech-recognition parts...
%PY% -m pip install mss pillow pynput sounddevice faster-whisper numpy pyttsx3
if errorlevel 1 ( echo Something failed to install. Check the internet connection and run this again. & pause & exit /b 1 )
echo Downloading the speech-recognition model ^(about 150 MB, one time only^)...
%PY% -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8'); print('ready')"
where ollama >nul 2>&1
if errorlevel 1 (
  echo Ollama isn't installed, so Piper can't look at the screen yet. Install Ollama from ollama.com, then run this again.
) else (
  echo Downloading the model that can see the screen: qwen2.5vl:7b ^(about 6 GB, one time only^)...
  ollama pull qwen2.5vl:7b
)
echo done> ".companion-setup-%COMPUTERNAME%"
echo === Piper on screen is ready ===
if /i not "%1"=="auto" pause
