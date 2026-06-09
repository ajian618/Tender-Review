$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) {
  $python = "py"
  $argsPrefix = @("-3.12")
} else {
  $argsPrefix = @()
}

Write-Host "== Install Python dependencies =="
& $python @argsPrefix -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created .env from .env.example. Please edit APP_PASSWORD and SESSION_SECRET. Configure DeepSeek with hermes setup or hermes model."
}

Write-Host "== Verify =="
& $python @argsPrefix -m pytest -q
.\scripts\doctor.ps1
