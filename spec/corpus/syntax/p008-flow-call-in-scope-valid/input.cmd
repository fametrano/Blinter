@echo off
goto :main
:sub
echo !A!
exit /b 0
:main
setlocal enabledelayedexpansion
set "A=1"
call :sub
endlocal
exit /b 0
