# MultiAIGroup 一键启动：后端 (FastAPI) + 前端 (Vite)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "未找到后端虚拟环境，正在创建..." -ForegroundColor Yellow
    py -3 -m venv (Join-Path $root "backend\.venv")
    $python = Join-Path $root "backend\.venv\Scripts\python.exe"
    & $python -m pip install -r (Join-Path $root "backend\requirements.txt")
}

if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Write-Host "未安装前端依赖，正在安装..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "frontend")
    npm install
    Pop-Location
}

Write-Host "启动后端 http://127.0.0.1:8765 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\backend'; & '$python' -m app.main"
)

Start-Sleep -Seconds 2

Write-Host "启动前端 http://localhost:5173 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\frontend'; npm run dev"
)
