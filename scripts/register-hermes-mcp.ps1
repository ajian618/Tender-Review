$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

hermes mcp remove bid-review 2>$null | Out-Null

$runner = Join-Path $root "scripts\bid-review-mcp.cmd"
$mcpArgs = @("mcp", "add", "bid-review", "--command", $runner)
"Y" | & hermes @mcpArgs
& hermes mcp list
