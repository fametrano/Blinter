@echo off
setlocal enabledelayedexpansion
set "A=%~1"
if "!A!"=="1" (
    endlocal
    goto :error
)
echo !A!
endlocal
exit /b 0
:error
exit /b 1
