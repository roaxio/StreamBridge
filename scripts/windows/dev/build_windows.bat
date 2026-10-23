@echo off
rem Build standalone StreamBridge for Windows from the venv (no Python needed on the user's PC).
rem   dist\onedir\StreamBridge\StreamBridge.exe   (folder, starts fastest)
rem   dist\onefile\StreamBridge.exe               (single file)
setlocal
cd /d "%~dp0..\..\.."
echo === StreamBridge: build_windows.bat (developer build, folder + single file) ===
echo This script will:
echo   1. Go to the repo's top folder and create .venv if it doesn't exist.
echo   2. Install StreamBridge with its dev tools into .venv (pip install -e ".[dev,keyring]").
echo   3. Build the folder version with PyInstaller (packaging\windows.spec) into dist\onedir.
echo   4. Build the single-file version the same way into dist\onefile.
echo.
call :maybe_pause
echo [1/3] Preparing .venv ...
if not exist ".venv\Scripts\python.exe" echo ^> py -3 -m venv .venv
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv || goto :fail
echo ^> .venv\Scripts\python.exe -m pip install -q -e ".[dev,keyring]"
".venv\Scripts\python.exe" -m pip install -q -e ".[dev,keyring]" || goto :fail
echo [2/3] Building folder version (onedir) ...
echo ^> .venv\Scripts\pyinstaller.exe --noconfirm --clean --distpath dist\onedir --workpath build\onedir packaging\windows.spec
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --distpath dist\onedir --workpath build\onedir packaging\windows.spec || goto :fail
echo [3/3] Building single-file version (onefile) ...
echo ^> .venv\Scripts\pyinstaller.exe --noconfirm --clean --distpath dist\onefile --workpath build\onefile packaging\windows.spec -- --onefile
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --distpath dist\onefile --workpath build\onefile packaging\windows.spec -- --onefile || goto :fail
echo.
echo BUILD OK. Built: dist\onedir\StreamBridge\StreamBridge.exe and dist\onefile\StreamBridge.exe
call :maybe_pause
exit /b 0
:fail
echo BUILD FAILED. See the messages above.
call :maybe_pause
exit /b 1
:maybe_pause
if "%STREAMBRIDGE_NO_PAUSE%"=="1" exit /b 0
echo Press any key to continue, or Ctrl+C to cancel . . .
pause >nul
exit /b 0
