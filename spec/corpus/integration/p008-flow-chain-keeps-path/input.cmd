@echo off
setlocal enabledelayedexpansion
set "A=1"
endlocal
dir || exit /b 1
echo !A!
exit /b 0
