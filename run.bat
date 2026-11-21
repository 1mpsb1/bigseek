@echo off
cd /d "%~dp0"

if exist "dist\BigSeek Desktop\BigSeek Desktop.exe" (
    start "" "dist\BigSeek Desktop\BigSeek Desktop.exe"
    exit /b
)

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"

if not defined PY (
    echo Python не найден.
    echo Запустите dist\BigSeek Desktop\BigSeek Desktop.exe
    echo или установите Python 3.10+.
    pause
    exit /b 1
)

"%PY%" main.py
if errorlevel 1 pause
