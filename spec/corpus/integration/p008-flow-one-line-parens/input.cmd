@echo off
if "%1"=="x" (call :s)
if "%1"=="a" (goto a) else (goto b)
exit /b 0
:a
echo !A!
exit /b 0
:b
echo !B!
exit /b 0
:s
echo !C!
exit /b 0
