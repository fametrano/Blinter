@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
endlocal
for /f "delims=" %%F in ('ver ^
  ^| find "zzzz"') do (
    goto :eof
)
:show
echo [!A!]
