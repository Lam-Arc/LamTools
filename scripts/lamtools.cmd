@echo off
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

py -3.14 --version >nul 2>&1
if %errorlevel%==0 (
  py -3.14 "%~dp0lamtools_cli.py" %*
  exit /b %errorlevel%
)

where python3 >nul 2>&1
if %errorlevel%==0 (
  python3 "%~dp0lamtools_cli.py" %*
  exit /b %errorlevel%
)

where python >nul 2>&1
if %errorlevel%==0 (
  python "%~dp0lamtools_cli.py" %*
  exit /b %errorlevel%
)

echo ERROR: No Python 3 found. Install Python 3 and ensure python/python3/py is on PATH.
exit /b 1
