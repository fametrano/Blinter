@echo off
setlocal enabledelayedexpansion
set "A=%~1"
:again
echo !A!
if "!A!"=="1" goto :again
endlocal
exit /b 0
