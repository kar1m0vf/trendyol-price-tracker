@echo off
REM Telegram Price Tracker Bot - Start Script for Windows

setlocal enabledelayedexpansion

echo ========================================
echo Telegram Price Tracker Bot - Windows
echo ========================================
echo.

REM Check if .env exists
if not exist ".env" (
    echo ERROR: .env file not found!
    echo Please create .env file with BOT_TOKEN
    echo Example:
    echo   BOT_TOKEN=your_token_here
    pause
    exit /b 1
)

REM Check if venv exists
if not exist "venv\" (
    echo ERROR: Virtual environment not found!
    echo Create it with: python -m venv venv
    pause
    exit /b 1
)

REM Check bot readiness
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

REM Start the bot
.\venv\Scripts\python.exe bot.py

REM If bot exits, show message
echo.
echo Bot has stopped.
pause
