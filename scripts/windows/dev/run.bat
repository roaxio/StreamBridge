@echo off
rem Windows: create/use .venv and start StreamBridge (window, or pass CLI flags).
setlocal
cd /d "%~dp0..\..\.."
echo === StreamBridge: run.bat (start the app from source) ===
echo This script will:
echo   1. Go to the repo's top folder: %CD%
echo   2. If .venv doesn't exist yet: check Python is 3.10-3.13, create .venv,
echo      upgrade pip and install StreamBridge into it (pip install -e .).
echo   3. Start StreamBridge: the window if no flags were given, otherwise the CLI.
echo.
call :maybe_pause
if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Creating Python virtual environment in .venv ...
  echo ^> py -3 -c "import sys; assert ..."  [checks Python 3.10-3.13]
  py -3 -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,13), 'Python 3.10-3.13 needed'" || goto :nopython
  echo ^> py -3 -m venv .venv
  py -3 -m venv .venv || goto :nopython
  echo ^> .venv\Scripts\python.exe -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  echo ^> .venv\Scripts\python.exe -m pip install -e .
  ".venv\Scripts\python.exe" -m pip install -e . || goto :fail
) else (
  echo [1/2] .venv already exists, skipping setup.
)
echo [2/2] Starting StreamBridge ...
if "%~1"=="" (
  echo ^> start "" .venv\Scripts\pythonw.exe -m streambridge
  start "" ".venv\Scripts\pythonw.exe" -m streambridge
) else (
  echo ^> .venv\Scripts\python.exe -m streambridge %*
  ".venv\Scripts\python.exe" -m streambridge %*
)
exit /b %errorlevel%
:nopython
echo Python 3.10-3.13 is needed: https://www.python.org/downloads/windows/  (tick "Add python.exe to PATH")
pause & exit /b 1
:fail
echo Installing the requirements failed. See the messages above.
pause & exit /b 1
:maybe_pause
if "%STREAMBRIDGE_NO_PAUSE%"=="1" exit /b 0
echo Press any key to continue, or Ctrl+C to cancel . . .
pause >nul
exit /b 0
