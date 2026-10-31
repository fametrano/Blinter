@echo off
setlocal enabledelayedexpansion
set "A=%~1"
if "!A!"=="1" (
    endlocal & set "R=%R%" & exit /b 1
)
if "!A!"=="3" (
    endlocal
    exit/b 1
)
if "!A!"=="2" (
    endlocal
    echo bye
    exit /b 1
)
echo !A!
endlocal
exit /b 0
