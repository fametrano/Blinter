@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
if "%~1"=="x" (
    endlocal
) else (echo leaving
    exit /b 1)
:show
echo [!A!]
