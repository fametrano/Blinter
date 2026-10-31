@echo off
setlocal enabledelayedexpansion
set A=1
set "fn=:show"
call :show
endlocal
call %fn%
exit /b
:show
echo [!A!]
exit /b
