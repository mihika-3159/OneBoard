# OneBoard: One-Click Startup Script (Windows PowerShell)
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Starting OneBoard: AI Operating System for a Company of One" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$ProjectRoot = Split-Path -Parent $PSScriptRoot

# 1. Start FastAPI Backend
Write-Host "`n[1/2] Starting FastAPI backend on http://localhost:8000..." -ForegroundColor Yellow
$BackendCmd = "cd '$ProjectRoot'; `$env:PYTHONPATH='.'; .venv\Scripts\uvicorn apps.api.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $BackendCmd

Start-Sleep -Seconds 2

# 2. Start Vite Frontend
Write-Host "`n[2/2] Starting React Vite frontend on http://localhost:5173..." -ForegroundColor Green
$FrontendCmd = "cd '$ProjectRoot\apps\web'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $FrontendCmd

Write-Host "`nOneBoard is launching!" -ForegroundColor Cyan
Write-Host "Backend API: http://localhost:8000" -ForegroundColor White
Write-Host "Swagger Docs: http://localhost:8000/docs" -ForegroundColor White
Write-Host "Web Application: http://localhost:5173" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan
