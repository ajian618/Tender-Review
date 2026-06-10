$ErrorActionPreference = "Continue"
$Utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (Test-Path ".env") {
  Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
      $name, $value = $line.Split("=", 2)
      $name = $name.Trim()
      $value = $value.Trim().Trim('"').Trim("'")
      if ($name -and $value) {
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
      }
    }
  }
}

$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) {
  $python = "py"
  $argsPrefix = @("-3.12")
} else {
  $argsPrefix = @()
}

Write-Host "== Python =="
& $python @argsPrefix --version

Write-Host "`n== Packages =="
@'
packages = ["fastapi", "uvicorn", "jinja2", "paddleocr", "paddle", "fitz", "qdrant_client", "fastembed", "mcp"]
for name in packages:
    try:
        mod = __import__(name)
        print(f"ok {name} {getattr(mod, '__version__', '')}")
    except Exception as exc:
        print(f"missing {name}: {exc}")
'@ | & $python @argsPrefix -

Write-Host "`n== Local enhanced parser =="
@'
import os
from pathlib import Path
from bid_agent.config import get_settings
from bid_agent.parsers import parse_document

settings = get_settings()
print(f"DOCUMENT_PARSER={settings.document_parser}")
print(f"DOCUMENT_LANGUAGE={settings.document_language}")

try:
    from paddleocr import PPStructureV3
    print("ok paddleocr.PPStructureV3")
except Exception as exc:
    print(f"missing PPStructureV3: {exc}")

try:
    from paddlex.utils.deps import require_extra
    require_extra("ocr", obj_name="PP-StructureV3")
    print("ok paddlex[ocr] extras")
except Exception as exc:
    print(f"missing paddlex[ocr] extras: {exc}")

try:
    from paddleocr._doc2md.core import convert
    print("ok paddleocr doc2md")
except Exception as exc:
    print(f"missing doc2md: {exc}")

cache_paths = [
    Path.home() / ".paddlex" / "official_models",
    Path.home() / ".paddleocr",
    Path.home() / ".cache",
]
for path in cache_paths:
    print(f"cache {path}: {'exists' if path.exists() else 'missing'}")

sample = Path("storage/parser_doctor_sample.txt")
sample.parent.mkdir(exist_ok=True)
sample.write_text("Sample tender requirement: bidder must provide qualification evidence.", encoding="utf-8")
result = parse_document(sample, engine=settings.document_parser, language=settings.document_language)
print(f"text parse: engine={result.engine} status={result.status} chunks={len(result.chunks)}")

smoke_file = os.getenv("PARSER_SMOKE_FILE", "").strip()
if smoke_file:
    path = Path(smoke_file)
    result = parse_document(path, engine=settings.document_parser, language=settings.document_language)
    print(f"deep parse: {path.name} engine={result.engine} status={result.status} chars={len(result.markdown)} chunks={len(result.chunks)}")
else:
    print("skip deep PDF/image parse: set PARSER_SMOKE_FILE to a local file path when you want to download/use structure models.")
'@ | & $python @argsPrefix -

Write-Host "`n== Vector and MCP layer =="
@'
from pathlib import Path
from bid_agent.config import get_settings

settings = get_settings()
print(f"VECTOR_ENABLED={settings.vector_enabled}")
print(f"VECTOR_STORE_DIR={settings.vector_store_dir}")
print(f"VECTOR_COLLECTION={settings.vector_collection}")
print(f"EMBEDDING_MODEL={settings.embedding_model}")
print(f"EMBEDDING_DIM={settings.embedding_dim}")
print(f"APP_BASE_URL={settings.app_base_url}")

try:
    import tempfile
    from qdrant_client import QdrantClient
    with tempfile.TemporaryDirectory(prefix="bid_qdrant_doctor_") as temp_dir:
        client = QdrantClient(path=temp_dir)
        print("ok local Qdrant client")
        client.close()
except Exception as exc:
    print(f"qdrant check failed: {exc}")

try:
    from mcp.server.fastmcp import FastMCP
    print("ok MCP SDK")
except Exception as exc:
    print(f"MCP SDK check failed: {exc}")
'@ | & $python @argsPrefix -

Write-Host "`n== Hermes =="
$hermesCommand = if ($env:HERMES_COMMAND) { $env:HERMES_COMMAND } else { "hermes" }
& $hermesCommand --version
Write-Host "Hermes config path:"
& $hermesCommand config path
Write-Host "Hermes env path:"
& $hermesCommand config env-path
Write-Host "Hermes MCP servers:"
& $hermesCommand mcp list
Write-Host "Hermes MCP bid-review test:"
& $hermesCommand mcp test bid-review

Write-Host "`n== App health =="
Write-Host "Run scripts\run-dev.ps1, then open http://127.0.0.1:8000/health"
