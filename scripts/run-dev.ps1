$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Starting Tender Review web app..."
Write-Host "Keep this PowerShell window open while using the site."
Write-Host "Open on this computer: http://127.0.0.1:8000"
Write-Host "LAN users should open: http://<this-computer-ip>:8000"
Write-Host "Do not open http://0.0.0.0:8000 in the browser; 0.0.0.0 only means the server listens on all network cards."
Write-Host ""

$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (Test-Path $python) {
  & $python -m bid_agent.app
} else {
  py -3.12 -m bid_agent.app
}
