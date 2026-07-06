# 一键启动：分别在两个新 PowerShell 窗口里拉起后端和前端。
# 用法：在项目根目录执行  .\start.ps1
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'scripts\set-utf8.ps1')

Start-Process powershell -ArgumentList @(
    "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", "`"$root\scripts\start-backend.ps1`""
)
Start-Process powershell -ArgumentList @(
    "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", "`"$root\scripts\start-frontend.ps1`""
)

Write-Host "已在两个新窗口启动后端(8000) 与 前端(5173)。" -ForegroundColor Green
Write-Host "稍候片刻，浏览器打开 http://localhost:5173" -ForegroundColor Green