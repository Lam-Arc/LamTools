@echo off
chcp 65001 >nul 2>&1
if not defined LAMTOOLS_CORE_DB set "LAMTOOLS_CORE_DB=%~dp0data\core.db"
call "%~dp0scripts\core.cmd" %*
