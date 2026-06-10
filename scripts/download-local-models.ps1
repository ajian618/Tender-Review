$ErrorActionPreference = "Stop"
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

@'
import os
from fastembed import TextEmbedding

embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
document_language = os.getenv("DOCUMENT_LANGUAGE", "ch")

print(f"Downloading/loading embedding model: {embedding_model}")
embedding = TextEmbedding(model_name=embedding_model)
list(embedding.embed(["bid review model warmup"]))
print("Embedding model ready.")

print(f"Downloading/loading PaddleOCR PPStructureV3 models, lang={document_language}")
try:
    from paddleocr import PPStructureV3

    PPStructureV3(
        lang=document_language,
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
        use_textline_orientation=True,
        use_table_recognition=True,
        use_formula_recognition=False,
        use_chart_recognition=False,
        use_seal_recognition=False,
    )
except Exception as exc:
    text = str(exc)
    if "requires additional dependencies" in text or "paddlex[ocr]" in text:
        print("")
        print("PPStructureV3 dependency check failed.")
        print("Run this once, then retry scripts/download-local-models.ps1:")
        print('  py -3.12 -m pip install -r requirements.txt')
        print("")
        print("Direct repair command:")
        print('  py -3.12 -m pip install "paddlex[ocr]==3.6.1"')
        print("")
    raise
print("PPStructureV3 models ready.")

print("Model cache locations:")
print(rf"  PaddleX: {os.path.expanduser('~/.paddlex/official_models')}")
print(rf"  HuggingFace/FastEmbed: {os.path.expanduser('~/.cache')}")
'@ | & $python @argsPrefix -
