@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
if "%~1"=="x" (
    endlocal
) else if "%~1"=="z" (
    echo z
) & exit /b
:show
echo [!A!]
