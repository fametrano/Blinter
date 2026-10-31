@echo off
setlocal enabledelayedexpansion
set "A=%~1"
endlocal
:next
echo !A!
exit /b 0
