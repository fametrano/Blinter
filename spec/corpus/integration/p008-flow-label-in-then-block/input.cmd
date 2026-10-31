@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
goto :inside
if "x"=="x" (
:inside
    echo in
) else (
    endlocal
)
:show
echo [!A!]
