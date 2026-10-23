@echo off
rem Lint, test and build the standalone Windows app, before you push.
setlocal
cd /d "%~dp0..\..\.."
echo === StreamBridge: check_all.bat (lint + tests + build, before you push) ===
echo This script will:
echo   1. Go to the repo's top folder, create .venv if needed and install
echo      StreamBridge with its dev tools (pip install -e ".[dev,keyring]").
echo   2. Lint the code with ruff.
echo   3. Run the full test suite with pytest.
echo   4. Run scripts\windows\dev\build_windows.bat (folder + single-file builds).
echo It stops at the first failure. You are asked to continue only once.
echo.
call :maybe_pause
set STREAMBRIDGE_NO_PAUSE=1
echo [1/4] Preparing .venv ...
if not exist ".venv\Scripts\python.exe" echo ^> py -3 -m venv .venv
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv || goto :fail
echo ^> .venv\Scripts\python.exe -m pip install -q -e ".[dev,keyring]"
".venv\Scripts\python.exe" -m pip install -q -e ".[dev,keyring]" || goto :fail
echo [2/4] Linting (ruff) ...
echo ^> .venv\Scripts\ruff.exe check .
".venv\Scripts\ruff.exe" check . || goto :fail
echo [3/4] Running tests (pytest) ...
echo ^> .venv\Scripts\python.exe -m pytest -q
".venv\Scripts\python.exe" -m pytest -q || goto :fail
echo [4/4] Building ...
echo ^> call scripts\windows\dev\build_windows.bat
call scripts\windows\dev\build_windows.bat || goto :fail
echo All checks passed.
exit /b 0
:fail
echo CHECKS FAILED. See the messages above.
exit /b 1
:maybe_pause
if "%STREAMBRIDGE_NO_PAUSE%"=="1" exit /b 0
echo Press any key to continue, or Ctrl+C to cancel . . .
pause >nul
exit /b 0
