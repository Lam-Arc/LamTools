@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
py -3.14 "members\writer\start.py" %*
set EXITCODE=%errorlevel%
if %EXITCODE% neq 0 (
    echo.
    echo 启动失败，按任意键关闭窗口...
    pause >nul
)
exit /b %EXITCODE%
