@echo off
rem Builds only the installer. Run build.bat first (or release.bat for everything).
cd /d "%~dp0.."

set "ISCC="
if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC where iscc >nul 2>nul && set "ISCC=iscc"

if not defined ISCC (
    echo Inno Setup not found. Install it from https://jrsoftware.org/isdl.php
    echo then run this file again.
    pause
    exit /b 1
)

if not exist "dist\BigSeek Desktop\BigSeek Desktop.exe" (
    echo dist\BigSeek Desktop\BigSeek Desktop.exe not found.
    echo Run build.bat first.
    pause
    exit /b 1
)

"%ISCC%" "installer\BigSeekDesktop.iss"
if errorlevel 1 (
    echo Installer build failed.
    pause
    exit /b 1
)

echo.
echo Done: release\BigSeek-Desktop-*-setup.exe
pause
