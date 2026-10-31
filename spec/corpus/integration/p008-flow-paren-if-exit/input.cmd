@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
endlocal
(if "%~1"=="x" exit /b)
:show
echo [!A!]
