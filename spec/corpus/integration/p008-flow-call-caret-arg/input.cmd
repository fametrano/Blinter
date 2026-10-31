@echo off
setlocal enabledelayedexpansion
set "A=1"
if "%~1"=="x" goto :show
endlocal
call prog.exe --flag ^
exit
:show
echo !A!
