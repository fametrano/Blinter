@echo off
setlocal enabledelayedexpansion
set "A=%~1"
if "!A!"=="1" (
    endlocal
    goto :done
)
exit /b 0
:done
echo !A!
exit /b 0
