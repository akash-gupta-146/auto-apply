@echo off
rem The one file to double-click. The first time it installs everything; every time it opens the control panel.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\jobapply.exe" (
  echo First time here: installing. This can take several minutes. Please wait...
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Minimal
  echo.
)
if not exist ".venv\Scripts\jobapply.exe" (
  echo The install did not finish. The lines above say why. Fix that, then double-click Start.bat again.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m jobapply panel
echo.
echo The control panel has closed.
pause
