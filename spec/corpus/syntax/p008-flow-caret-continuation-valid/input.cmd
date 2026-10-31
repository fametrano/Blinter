@echo off
for /f "delims=" %%F in (`powershell -NoProfile ^
    -Command "Get-Date"`) do (
    set "D=%%F"
)
setlocal enabledelayedexpansion
set "A=%~1"
if "!A!"=="1" (
    endlocal
    exit /b 1
)
echo !A!
endlocal
exit /b 0
