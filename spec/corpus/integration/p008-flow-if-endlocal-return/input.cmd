@echo off
setlocal enabledelayedexpansion
set "VAL=x"
if defined VAL endlocal & set "RET=!VAL!"
exit /b 0
