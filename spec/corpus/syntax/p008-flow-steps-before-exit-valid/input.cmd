@echo off
setlocal enabledelayedexpansion
set "A=%~1"
if "!A!"=="1" (
    endlocal
    popd
    exit /b 1
)
if "!A!"=="2" (
    echo two
    ) else (
    echo !A!
)
echo !A!
endlocal
exit /b 0
