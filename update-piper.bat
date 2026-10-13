@echo off
setlocal
cd /d "%~dp0"
title Piper update
echo.
echo  Piper update: installs the newest piper-complete zip from your Downloads folder.
echo.
netstat -ano | findstr /R /C:":8790 .*LISTENING" >nul
if %errorlevel%==0 (
  echo  Piper is still running. Close the black Piper window first, then run this again.
  echo.
  pause
  exit /b 1
)
set "T=%TEMP%\piper-update"
if exist "%T%" rmdir /s /q "%T%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$z = Get-ChildItem -Path (Join-Path $env:USERPROFILE 'Downloads') -Filter 'piper-complete*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -First 1;" ^
  "if (-not $z) { Write-Host '  No piper-complete zip found in Downloads.'; exit 1 };" ^
  "Write-Host ('  Using ' + $z.Name + ', downloaded ' + $z.LastWriteTime);" ^
  "Expand-Archive -LiteralPath $z.FullName -DestinationPath (Join-Path $env:TEMP 'piper-update') -Force;" ^
  "if (-not (Test-Path (Join-Path $env:TEMP 'piper-update\piper\server.py'))) { Write-Host '  That zip does not look like Piper.'; exit 1 }"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)
rem An old copy pasted one folder too deep confuses Python: move it out of the way (nothing is deleted).
if exist "%~dp0piper\server.py" (
  if exist "%~dp0old-copy-piper" rmdir /s /q "%~dp0old-copy-piper"
  move "%~dp0piper" "%~dp0old-copy-piper" >nul
  echo  Moved an old copy found at piper\piper to old-copy-piper. You can delete it.
)
robocopy "%T%\piper" "%~dp0." /E /NFL /NDL /NJH /NJS /NP >nul
if %errorlevel% GEQ 8 (
  echo  Copying failed. Is a Piper file open in another program?
  pause
  exit /b 1
)
rmdir /s /q "%T%"
for /f "tokens=2 delims==" %%v in ('findstr /B /C:"BUILD = " server.py') do set "B=%%v"
echo.
echo  Updated to:%B%
echo  Your memories, settings and accounts were not touched.
echo.
echo  Starting Piper...
call "%~dp0start-piper.bat"
