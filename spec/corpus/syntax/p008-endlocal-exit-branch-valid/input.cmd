@echo off
setlocal enabledelayedexpansion
set "A=%~1"
if "!A!"=="1" (
    endlocal
    exit /b 1
)
if "!A!"=="2" endlocal & exit /b 2
if "!A!"=="3" (
    endlocal
    goto :eof
)
echo !A!
endlocal
exit /b 0
