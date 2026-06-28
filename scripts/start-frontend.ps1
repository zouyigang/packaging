# 启动前端（Vite 开发服务器），监听 5173，已配 /api -> 后端 8000 代理。
# 首次会自动 npm install。用法：.\scripts\start-frontend.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location (Join-Path $root "frontend")

if (-not (Test-Path "node_modules")) {
    Write-Host "首次运行，安装前端依赖（npm install）..." -ForegroundColor Yellow
    npm install
}

Write-Host "前端启动中：http://localhost:5173" -ForegroundColor Cyan
npm run dev
