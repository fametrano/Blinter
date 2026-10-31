@echo off
setlocal enabledelayedexpansion
set "VAL=x"
mkdir out || endlocal & echo failed !VAL!
exit /b 0
