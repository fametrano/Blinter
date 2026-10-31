@echo off
setlocal enabledelayedexpansion
set "A=%~1"
if defined B (
    endlocal
    exit.bat
)
echo !A!
exit /b 0
