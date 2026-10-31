@echo off
if "%1"=="a" (
    setlocal enabledelayedexpansion
    set V=1
    echo !V!
    endlocal
    exit /b 0
)
echo !V!
