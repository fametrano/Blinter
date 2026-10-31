@echo off
setlocal enabledelayedexpansion
set "A=1"
if "%~1"=="x" (
  endlocal
  goto :eof
)
call :sub"x"
exit /b
:sub
echo !A!
exit /b
