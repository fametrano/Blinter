@echo off
setlocal enabledelayedexpansion
set A=1
set "go=goto :show"
call :show
endlocal
%go%
exit /b
:show
echo [!A!]
exit /b
