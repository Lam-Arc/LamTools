@echo off
chcp 65001 >nul 2>&1
set "LAMTOOLS_ROOT=%~dp0.."
set "PYTHONPATH=%LAMTOOLS_ROOT%\core\src;%PYTHONPATH%"
if not defined LAMTOOLS_LLM_CONFIG_DB if exist "%LAMTOOLS_ROOT%\data\lamtools.db" set "LAMTOOLS_LLM_CONFIG_DB=%LAMTOOLS_ROOT%\data\lamtools.db"
py -3.14 -m lamtools_core.cli %*
if %ERRORLEVEL% EQU 0 exit /b 0
python -m lamtools_core.cli %*
if %ERRORLEVEL% EQU 0 exit /b 0
python3 -m lamtools_core.cli %*
exit /b %ERRORLEVEL%
