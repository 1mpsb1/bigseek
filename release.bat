@echo off
rem One-click release build: exe + portable ZIP + installer + checksums.
rem Everything lands in the "release" folder (not committed to git).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_release.ps1" %*
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)
echo.
pause
