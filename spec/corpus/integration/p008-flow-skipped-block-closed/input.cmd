@echo off
setlocal enabledelayedexpansion
set "A=%~1"
endlocal
if "%~1"=="1" (
    exit /b 1
)
echo !A!
exit /b 0
