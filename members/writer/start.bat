@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
py -3.14 "start.py" %*
exit /b %errorlevel%
