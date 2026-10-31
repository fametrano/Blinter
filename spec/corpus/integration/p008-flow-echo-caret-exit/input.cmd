@echo off
setlocal enabledelayedexpansion
set "A=1"
if "%~1"=="x" goto :show
endlocal
echo ^
exit /b
:show
echo !A!
