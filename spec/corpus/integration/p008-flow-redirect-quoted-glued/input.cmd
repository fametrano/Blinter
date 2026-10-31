@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="y" goto :show
endlocal
>"%TEMP%\a b.txt"exit /b
:show
echo [!A!]
