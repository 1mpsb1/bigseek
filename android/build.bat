@echo off
rem Builds the BigSeek Android APK without Gradle.
rem Pass -Install -Launch to put it on the connected phone and open it.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_apk.ps1" %*
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)
echo.
pause
