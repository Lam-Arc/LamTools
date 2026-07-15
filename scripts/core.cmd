@echo off
chcp 65001 >nul 2>&1
set "LAMTOOLS_ROOT=%~dp0.."
set "PYTHONPATH=%LAMTOOLS_ROOT%\core\src;%PYTHONPATH%"
if not defined LAMTOOLS_LLM_CONFIG_DB if exist "%LAMTOOLS_ROOT%\data\lamtools.db" set "LAMTOOLS_LLM_CONFIG_DB=%LAMTOOLS_ROOT%\data\lamtools.db"
if not defined LAMTOOLS_CORE_DB set "LAMTOOLS_CORE_DB=%LAMTOOLS_ROOT%\data\core.db"

set "LAMTOOLS_PYTHON=py -3.14"
%LAMTOOLS_PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 goto run
set "LAMTOOLS_PYTHON=python"
%LAMTOOLS_PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 goto run
set "LAMTOOLS_PYTHON=python3"
%LAMTOOLS_PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 goto run
echo error: Python 3.14 or newer is required 1>&2
exit /b 1

:run
%LAMTOOLS_PYTHON% -m lamtools_core.cli %*
exit /b %ERRORLEVEL%
