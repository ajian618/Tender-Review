$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$template = Join-Path $root "config\hermes\default-SOUL.md"
if (-not (Test-Path -LiteralPath $template)) {
  throw "SOUL template not found: $template"
}

$hermes = Get-Command hermes -ErrorAction SilentlyContinue
if (-not $hermes) {
  throw "Cannot find 'hermes' in PATH. Open a new PowerShell window after installing Hermes, or add Hermes to PATH."
}

$configPath = (& hermes config path | Select-Object -First 1).Trim()
if (-not $configPath -or -not (Test-Path -LiteralPath $configPath)) {
  throw "Hermes config file not found: $configPath"
}

$hermesHome = Split-Path -Parent $configPath
$soulPath = Join-Path $hermesHome "SOUL.md"

Write-Host "Project root: $root"
Write-Host "Hermes command: $($hermes.Source)"
Write-Host "Hermes home: $hermesHome"
Write-Host "SOUL target: $soulPath"

if (Test-Path -LiteralPath $soulPath) {
  $backupPath = "$soulPath.bid-review-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
  Copy-Item -LiteralPath $soulPath -Destination $backupPath -Force
  Write-Host "Backup written: $backupPath"
}

$content = [System.IO.File]::ReadAllText($template, [System.Text.Encoding]::UTF8)
[System.IO.File]::WriteAllText($soulPath, $content, $Utf8NoBom)

Write-Host "Hermes default SOUL.md installed."
