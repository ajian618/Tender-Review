$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Project root: $root"

$hermes = Get-Command hermes -ErrorAction SilentlyContinue
if (-not $hermes) {
  throw "Cannot find 'hermes' in PATH. Open a new PowerShell window after installing Hermes, or add Hermes to PATH."
}
Write-Host "Hermes command: $($hermes.Source)"

$runner = Join-Path $root "scripts\bid-review-mcp.cmd"
if (-not (Test-Path -LiteralPath $runner)) {
  throw "MCP runner not found: $runner"
}
Write-Host "MCP runner: $runner"

$configPath = (& hermes config path | Select-Object -First 1).Trim()
if (-not $configPath -or -not (Test-Path -LiteralPath $configPath)) {
  throw "Hermes config file not found: $configPath"
}
Write-Host "Hermes config: $configPath"

$backupPath = "$configPath.bid-review-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath $configPath -Destination $backupPath -Force
Write-Host "Backup written: $backupPath"

$rawLines = [System.IO.File]::ReadAllLines($configPath, [System.Text.Encoding]::UTF8)
$lines = [System.Collections.Generic.List[string]]::new()
foreach ($line in $rawLines) {
  $lines.Add($line)
}

$escapedRunner = $runner.Replace("'", "''")
$childBlock = @(
  "  bid-review:",
  "    command: '$escapedRunner'",
  "    enabled: true"
)
$fullBlock = @(
  "mcp_servers:"
) + $childBlock

$mcpIndex = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -match '^mcp_servers:\s*$') {
    $mcpIndex = $i
    break
  }
}

if ($mcpIndex -lt 0) {
  if ($lines.Count -gt 0 -and $lines[$lines.Count - 1].Trim()) {
    $lines.Add("")
  }
  foreach ($line in $fullBlock) {
    $lines.Add($line)
  }
} else {
  $mcpEnd = $lines.Count
  for ($i = $mcpIndex + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\S') {
      $mcpEnd = $i
      break
    }
  }

  $bidIndex = -1
  for ($i = $mcpIndex + 1; $i -lt $mcpEnd; $i++) {
    if ($lines[$i] -match '^  bid-review:\s*$') {
      $bidIndex = $i
      break
    }
  }

  if ($bidIndex -lt 0) {
    for ($i = $childBlock.Count - 1; $i -ge 0; $i--) {
      $lines.Insert($mcpEnd, $childBlock[$i])
    }
  } else {
    $bidEnd = $mcpEnd
    for ($i = $bidIndex + 1; $i -lt $mcpEnd; $i++) {
      if ($lines[$i] -match '^  [^ ].*:\s*$') {
        $bidEnd = $i
        break
      }
    }
    $removeCount = $bidEnd - $bidIndex
    $lines.RemoveRange($bidIndex, $removeCount)
    for ($i = $childBlock.Count - 1; $i -ge 0; $i--) {
      $lines.Insert($bidIndex, $childBlock[$i])
    }
  }
}

$content = ($lines -join [Environment]::NewLine) + [Environment]::NewLine
[System.IO.File]::WriteAllText($configPath, $content, $Utf8NoBom)
Write-Host "bid-review MCP registration written without interactive prompts."

Write-Host "Current Hermes MCP list:"
& hermes mcp list

Write-Host "Testing bid-review MCP:"
& hermes mcp test bid-review
