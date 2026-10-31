@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
endlocal
goto :inside
if "x"=="y" (
:inside
    echo in
) & exit /b
:show
echo [!A!]
