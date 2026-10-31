@echo off
setlocal enabledelayedexpansion
set A=1
call :show
endlocal
call ,:show
exit /b
:show
echo [!A!]
exit /b
