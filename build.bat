@echo off
cd /d "%~dp0"

rem Builds only the executable folder (dist\BigSeek Desktop).
rem For the installer and portable ZIP use release.bat.

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"

if not defined PY (
    echo Python 3.10+ not found.
    pause
    exit /b 1
)

"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r "%~dp0requirements.txt"
"%PY%" -m pip install --upgrade "pyinstaller>=6.10"

"%PY%" -m PyInstaller --noconfirm --clean --windowed ^
    --name "BigSeek Desktop" ^
    --icon "%~dp0assets\app.ico" ^
    --add-data "%~dp0version.txt;." ^
    --workpath "%~dp0build\work" ^
    --specpath "%~dp0build" ^
    --distpath "%~dp0dist" ^
    "%~dp0main.py"

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Done: dist\BigSeek Desktop\BigSeek Desktop.exe
echo For the installer and portable ZIP run release.bat
pause
