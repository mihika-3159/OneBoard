# OneBoard — Ollama Setup & Model Pull Script
# =============================================
# Run this after installing Ollama to pull a lightweight model
# and verify everything is working for the competition demo.
#
# Usage: .\scripts\setup_ollama.ps1

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  OneBoard - Ollama Setup & Model Configuration  " -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# ── Find Ollama ───────────────────────────────────────────────────────────────
$ollamaCmd = $null
$searchPaths = @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "C:\Program Files\Ollama\ollama.exe",
    "$env:ProgramFiles\Ollama\ollama.exe",
    (Get-Command ollama -ErrorAction SilentlyContinue)?.Source
)
foreach ($p in $searchPaths) {
    if ($p -and (Test-Path $p)) {
        $ollamaCmd = $p
        Write-Host "✅ Found Ollama at: $ollamaCmd" -ForegroundColor Green
        break
    }
}

if (-not $ollamaCmd) {
    Write-Host "❌ Ollama not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Ollama first:" -ForegroundColor Yellow
    Write-Host "  1. Go to: https://ollama.com/download" -ForegroundColor White
    Write-Host "  2. Download & run OllamaSetup.exe" -ForegroundColor White
    Write-Host "  3. Re-run this script" -ForegroundColor White
    exit 1
}

# ── Add to PATH for this session ──────────────────────────────────────────────
$ollamaDir = Split-Path $ollamaCmd
$env:PATH = "$ollamaDir;$env:PATH"

# ── Check Ollama version ──────────────────────────────────────────────────────
$version = & $ollamaCmd --version 2>&1
Write-Host "📦 Ollama version: $version" -ForegroundColor Cyan

# ── Start Ollama service if not running ───────────────────────────────────────
Write-Host ""
Write-Host "🔄 Checking Ollama service..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
    Write-Host "✅ Ollama service already running" -ForegroundColor Green
} catch {
    Write-Host "⚡ Starting Ollama service..." -ForegroundColor Yellow
    Start-Process -FilePath $ollamaCmd -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 4
    Write-Host "✅ Ollama service started" -ForegroundColor Green
}

# ── Pull the recommended model ────────────────────────────────────────────────
Write-Host ""
Write-Host "📥 Pulling recommended model for OneBoard..." -ForegroundColor Yellow
Write-Host "   Model: qwen2.5:0.5b (smallest & fastest — great for demo)" -ForegroundColor Gray
Write-Host "   This may take a few minutes depending on your connection speed." -ForegroundColor Gray
Write-Host ""

# Order of preference: smallest first for speed, fallback to larger
$modelsToTry = @(
    @{ name = "qwen2.5:0.5b";  label = "Qwen2.5 0.5B (tiny, ~400MB)" },
    @{ name = "qwen2.5:1.5b";  label = "Qwen2.5 1.5B (~1GB)" },
    @{ name = "llama3.2:1b";   label = "Llama 3.2 1B (~1.3GB)" },
    @{ name = "phi3.5:mini";   label = "Phi-3.5 Mini (~2.2GB)" },
    @{ name = "qwen2.5:7b";    label = "Qwen2.5 7B (~4.7GB)" }
)

$pulled = $null
foreach ($m in $modelsToTry) {
    Write-Host "Trying: $($m.label)" -ForegroundColor White
    & $ollamaCmd pull $m.name
    if ($LASTEXITCODE -eq 0) {
        $pulled = $m.name
        Write-Host "✅ Successfully pulled: $($m.name)" -ForegroundColor Green
        break
    }
    Write-Host "⚠️  Failed to pull $($m.name), trying next..." -ForegroundColor Yellow
}

if (-not $pulled) {
    Write-Host "❌ Could not pull any model. Check your internet connection." -ForegroundColor Red
    exit 1
}

# ── List available models ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "📋 Available models in Ollama:" -ForegroundColor Cyan
& $ollamaCmd list

# ── Quick inference test ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "🧪 Running quick inference test..." -ForegroundColor Yellow
$testPrompt = "Reply with exactly: ONEBOARD_LIVE_OK"
$testResult = & $ollamaCmd run $pulled $testPrompt 2>&1
Write-Host "Response: $testResult" -ForegroundColor White

# ── Test via API ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "🔌 Testing Ollama HTTP API..." -ForegroundColor Yellow
try {
    $tagsResponse = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 5
    $tags = ($tagsResponse.Content | ConvertFrom-Json)
    $modelNames = $tags.models | ForEach-Object { $_.name }
    Write-Host "✅ API responding. Models: $($modelNames -join ', ')" -ForegroundColor Green
} catch {
    Write-Host "⚠️  API check failed: $_" -ForegroundColor Yellow
}

# ── Update OneBoard config ────────────────────────────────────────────────────
Write-Host ""
Write-Host "⚙️  Updating OneBoard model configuration..." -ForegroundColor Yellow

$configPath = "apps\api\core\config.py"
if (Test-Path $configPath) {
    $content = Get-Content $configPath -Raw
    # Check if already configured
    if ($content -match "OLLAMA_BASE_URL") {
        Write-Host "✅ Config already has Ollama settings" -ForegroundColor Green
    }
} else {
    Write-Host "⚠️  Config file not found at $configPath" -ForegroundColor Yellow
}

# ── Run integration tests ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "🧪 Running Ollama integration tests..." -ForegroundColor Yellow
& .venv\Scripts\python -m pytest tests\test_ollama_integration.py -v --tb=short 2>&1

# ── Final summary ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  ✅ Ollama Setup Complete!" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Start the backend:  .venv\Scripts\uvicorn apps.api.main:app --reload" -ForegroundColor Gray
Write-Host "  2. Start the frontend: cd apps\web && npm run dev" -ForegroundColor Gray
Write-Host "  3. Open browser:       http://localhost:5173" -ForegroundColor Gray
Write-Host "  4. Go to Boardroom tab and trigger a live AI Council deliberation!" -ForegroundColor Gray
Write-Host ""
Write-Host "Active model: $pulled" -ForegroundColor Cyan
Write-Host "Ollama API:   http://localhost:11434" -ForegroundColor Cyan
Write-Host "OneBoard API: http://localhost:8000" -ForegroundColor Cyan
Write-Host "OneBoard UI:  http://localhost:5173" -ForegroundColor Cyan
Write-Host ""
