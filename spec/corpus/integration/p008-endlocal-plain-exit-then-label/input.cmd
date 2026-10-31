@echo off
call :other
setlocal enabledelayedexpansion
set "A=1"
endlocal
exit /b 0
:other
echo !B!
exit /b 0
