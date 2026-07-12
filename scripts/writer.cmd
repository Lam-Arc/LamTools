@echo off
chcp 65001 >nul 2>&1
py -3.14 "%~dp0member_cli.py" writer %*
exit /b %ERRORLEVEL%
