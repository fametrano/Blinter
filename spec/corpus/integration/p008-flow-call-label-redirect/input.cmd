@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
endlocal
call :show>nul
exit /b
:show
echo [!A!]
