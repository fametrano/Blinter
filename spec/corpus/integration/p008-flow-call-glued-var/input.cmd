@echo off
setlocal enabledelayedexpansion
set A=1
set "fn=:show"
if "%~1"=="y" goto :show
endlocal
call%fn%
exit /b
:show
echo [!A!]
