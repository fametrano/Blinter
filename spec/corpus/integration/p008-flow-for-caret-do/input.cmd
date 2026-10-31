@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
endlocal
for %%i in (%~2) do ^
goto :eof
:show
echo [!A!]
