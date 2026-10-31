@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
endlocal
ver >nul & if "%~1"=="x" (echo bye
    exit /b 1)
:show
echo [!A!]
