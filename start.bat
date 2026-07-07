@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Check if already running
curl -s http://127.0.0.1:6173/api/projects >nul 2>&1
if %errorlevel%==0 (
    echo [OK] LamWriter is already running!
    echo Opening browser...
    start http://localhost:6174
    exit /b 0
)

REM Auto-setup if venv doesn't exist
if not exist "members\writer\venv\Scripts\python.exe" (
    echo ==========================================
    echo   LamWriter First-time Setup
    echo ==========================================
    echo.
    
    REM Check Python
    py -3.14 --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python 3.14 not found!
        echo Please install Python 3.14 from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo [OK] Python 3.14 found
    
    REM Check Node.js
    node --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Node.js not found!
        echo Please install Node.js LTS from https://nodejs.org/
        pause
        exit /b 1
    )
    echo [OK] Node.js found
    
    REM Create virtual environment
    echo.
    echo [1/4] Creating Python venv...
    py -3.14 -m venv members\writer\venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv!
        pause
        exit /b 1
    )
    echo [OK] venv ready
    
    REM Install backend dependencies
    echo.
    echo [2/4] Installing backend dependencies...
    members\writer\venv\Scripts\pip install -r members\writer\backend\requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install backend deps!
        pause
        exit /b 1
    )
    echo [OK] Backend deps installed
    
    REM Install frontend dependencies
    echo.
    echo [3/4] Installing frontend dependencies...
    cd members\writer\frontend
    if not exist "node_modules" (
        npm install
        if errorlevel 1 (
            echo [ERROR] Failed to install frontend deps!
            pause
            exit /b 1
        )
    ) else (
        echo [OK] Frontend deps already exist, skipping
    )
    cd ..\..\..
    echo [OK] Frontend deps ready
    
    REM Create data directory
    echo.
    echo [4/4] Creating data directory...
    mkdir members\writer\data 2>nul
    echo [OK] Data directory created
    
    echo.
    echo ==========================================
    echo Setup complete!
    echo.
    echo Please close this window and run start.bat again.
    echo ==========================================
    pause
    exit /b 0
)

REM Start LamWriter
py -3.14 "members\writer\start.py"
