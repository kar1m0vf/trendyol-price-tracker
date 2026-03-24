@echo off

setlocal enabledelayedexpansion

echo ========================================
echo Telegram Price Tracker Bot - Windows
echo ========================================
echo.

if not exist ".env" (
    echo ERROR: .env file not found!
    echo Please create .env file with BOT_TOKEN
    echo Example:
    echo   BOT_TOKEN=your_token_here
    pause
    exit /b 1
)

if not exist "venv\" (
    echo ERROR: Virtual environment not found!
    echo Create it with: python -m venv venv
    pause
    exit /b 1
)

echo Checking bot readiness...
echo.
.\venv\Scripts\python.exe check_bot_ready.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: Bot readiness check failed!
    echo Please fix the issues above.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Starting bot...
echo ========================================
echo.

.\venv\Scripts\python.exe bot.py

echo.
echo Bot has stopped.
pause
