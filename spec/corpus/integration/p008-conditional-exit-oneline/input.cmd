@echo off
setlocal enabledelayedexpansion
set "A=%~1"
if defined B endlocal
if errorlevel 1 exit /b 1
echo !A!
exit /b 0
