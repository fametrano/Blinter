@echo off
setlocal enabledelayedexpansion
set A=1
call :show
endlocal
for %%L in (:show) do call %%L
exit /b
:show
echo [!A!]
exit /b
