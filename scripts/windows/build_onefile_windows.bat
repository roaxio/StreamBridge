@echo off
rem Single-file Windows build, same as .github/workflows/release.yml (reference for the GitHub release):
rem   dist\StreamBridge.exe  +  release_assets\StreamBridge-v<version>-windows-x64.zip
rem For the developer onedir+onefile build see scripts\windows\dev\build_windows.bat.
rem Zips with 7-Zip like CI if 7z is on PATH, otherwise with Windows' built-in tar.exe.
setlocal
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv || goto :fail
".venv\Scripts\python.exe" -m pip install -q -e ".[dev,keyring]" || goto :fail
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --distpath dist --workpath build packaging\windows.spec -- --onefile || goto :fail
for /f %%v in ('".venv\Scripts\python.exe" -c "import streambridge; print(streambridge.__version__)"') do set "TAG=v%%v"
set "NAME=StreamBridge-%TAG%-windows-x64.zip"
set "STAGE=stage\StreamBridge-%TAG%"
if exist stage rmdir /s /q stage
mkdir "%STAGE%" || goto :fail
if not exist release_assets mkdir release_assets
if exist "release_assets\%NAME%" del "release_assets\%NAME%"
copy /y dist\StreamBridge.exe "%STAGE%\" >nul || goto :fail
copy /y packaging\user\windows\READ-ME-FIRST.txt "%STAGE%\" >nul || goto :fail
pushd stage
where 7z >nul 2>&1 && (7z a -tzip "..\release_assets\%NAME%" "StreamBridge-%TAG%" >nul) || (tar -a -c -f "..\release_assets\%NAME%" "StreamBridge-%TAG%")
set "RC=%errorlevel%"
popd
rmdir /s /q stage
if not "%RC%"=="0" goto :fail
echo.
echo Built: dist\StreamBridge.exe and release_assets\%NAME%
exit /b 0
:fail
echo Build failed. See the messages above.
exit /b 1
