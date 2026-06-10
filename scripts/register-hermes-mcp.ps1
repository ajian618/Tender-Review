$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$baseUrl = if ($env:APP_BASE_URL) { $env:APP_BASE_URL } else { "http://127.0.0.1:8000" }
$envArgs = @(
  "BID_AGENT_BASE_URL=$baseUrl"
)
if ($env:AGENT_TOOL_TOKEN) {
  $envArgs += "AGENT_TOOL_TOKEN=$env:AGENT_TOOL_TOKEN"
}

hermes mcp remove bid-review 2>$null | Out-Null

$runner = Join-Path $root "scripts\bid-review-mcp.cmd"
$mcpArgs = @("mcp", "add", "bid-review", "--command", $runner, "--env")
$mcpArgs += $envArgs
"Y" | & hermes @mcpArgs
& hermes mcp list
