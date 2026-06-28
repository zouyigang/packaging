# 启动后端（FastAPI / uvicorn），监听 8000，代码改动自动重载。
# 用法：右键「用 PowerShell 运行」，或在终端执行 .\scripts\start-backend.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location (Join-Path $root "backend")

Write-Host "后端启动中：http://127.0.0.1:8000  （文档 /docs）" -ForegroundColor Cyan
# --no-capture-output：直接透传子进程输出，避免 conda run 在 Windows 下用 GBK 重打印中文崩溃
conda run --no-capture-output -n packaging uvicorn app.main:app --port 8000 --reload
