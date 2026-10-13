@echo off
title Piper setup
cd /d "%~dp0"
echo.
echo === Piper setup (only needed once per PC) ===
echo.
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
  echo Python isn't installed. Installing Python 3.12 automatically...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo.
    echo Couldn't install automatically. Please install Python 3.12 from https://www.python.org/downloads/
    echo and tick "Add Python to PATH". Then double-click start-piper.bat again.
    start "" https://www.python.org/downloads/
    pause & exit /b
  )
  echo.
  echo Python installed. Close this window and double-click start-piper.bat again.
  pause & exit /b
)
echo Installing voice, secure storage and document readers...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install keyring kokoro-onnx soundfile numpy pypdf python-docx
if errorlevel 1 (
  echo.
  echo The voice engine couldn't install on this Python version.
  echo Piper still works, using the browser voice. For the British voice, install Python 3.12.
)
echo Installing the ZIM library reader (Kiwix files)...
%PY% -m pip install libzim
if errorlevel 1 echo   ZIM reader unavailable on this Python version. Python 3.12 is recommended.
%PY% -m pip install pyarrow >nul 2>&1
if not exist "models\kokoro-v1.0.int8.onnx" (
  echo Downloading the British voice model ^(about 120 MB, one time only^)...
  %PY% voice.py download
)
echo.
echo === Piper's brain (lets Piper hold real conversations) ===
where ollama >nul 2>&1
if not errorlevel 1 (
  echo Ollama is installed on this PC, so Piper will use it.
  if /i "%1"=="auto" goto brain_done
  choice /c YN /n /m "Also put a built-in brain inside Piper's folder so it works on PCs without Ollama? [Y/N] "
  if errorlevel 2 goto brain_done
)
%PY% setup_brain.py
:brain_done
call install-companion.bat auto
call install-knowledge.bat auto
echo done> ".setup-done-%COMPUTERNAME%"
echo.
echo === Setup complete ===
if /i not "%1"=="auto" pause
