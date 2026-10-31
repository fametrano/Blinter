@echo off
call :sub
setlocal enabledelayedexpansion
set "A=1"
endlocal
exit /b 0
:sub
echo !A!
exit /b 0
