@echo off
setlocal enabledelayedexpansion
set A=1
if "%~1"=="x" setlocal disabledelayedexpansion & echo [!A!]
