
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Telegram Price Tracker Bot - Windows PowerShell" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path ".env")) {
    Write-Host "ERROR: .env file not found!" -ForegroundColor Red
    Write-Host "Please create .env file with BOT_TOKEN" -ForegroundColor Yellow
    Write-Host "Example:" -ForegroundColor Yellow
    Write-Host "  BOT_TOKEN=your_token_here" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path "venv")) {
    Write-Host "ERROR: Virtual environment not found!" -ForegroundColor Red
    Write-Host "Create it with: python -m venv venv" -ForegroundColor Yellow
    exit 1
}

Write-Host "Checking bot readiness..." -ForegroundColor Yellow
Write-Host ""

$readinessOutput = & .\venv\Scripts\python.exe check_bot_ready.py
Write-Host $readinessOutput

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Bot readiness check failed!" -ForegroundColor Red
    Write-Host "Please fix the issues above." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Starting bot..." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

& .\venv\Scripts\python.exe bot.py

Write-Host ""
Write-Host "Bot has stopped." -ForegroundColor Yellow
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
