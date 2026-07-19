@echo off
chcp 65001 >nul 2>&1
py -3.14 "%~dp0scripts\member_cli.py" sage %*
