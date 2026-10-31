@echo off
setlocal enabledelayedexpansion
set "A=%~1"
if "!A!"=="1" (
    endlocal
    goto :join
)
endlocal
:join
echo !A!
exit /b 0
