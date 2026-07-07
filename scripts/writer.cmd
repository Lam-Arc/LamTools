@echo off
chcp 65001 >nul 2>&1
REM Try python3, then python, then py -3 (Windows launcher)
python3 "%~dp0scripts\member_cli.py" writer %* 2>nul && exit /b
python  "%~dp0scripts\member_cli.py" writer %* 2>nul && exit /b
py -3   "%~dp0scripts\member_cli.py" writer %* 2>nul && exit /b
echo ERROR: No Python 3 found. Install Python 3 and ensure python/python3/py is on PATH.
exit /b 1
