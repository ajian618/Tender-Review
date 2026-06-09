$ErrorActionPreference = "Continue"
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

Write-Host "== Python =="
& $python @argsPrefix --version

Write-Host "`n== Packages =="
@'
packages = ["fastapi", "uvicorn", "jinja2", "pdfplumber", "docx", "openpyxl", "paddleocr", "paddle", "fitz"]
for name in packages:
    try:
        __import__(name)
        print(f"ok {name}")
    except Exception as exc:
        print(f"missing {name}: {exc}")
'@ | & $python @argsPrefix -

Write-Host "`n== Hermes =="
hermes --version

Write-Host "`n== PDF extraction smoke test =="
@'
from pathlib import Path
from bid_agent.extractors import extract_document
pdfs = list(Path(".").glob("*.pdf"))
if not pdfs:
    print("skip: no pdf in current directory")
else:
    chunks, ocr_status = extract_document(pdfs[0], ocr_enabled=False, ocr_language="ch")
    print(f"ok {pdfs[0].name}: chunks={len(chunks)} chars={sum(len(c['text']) for c in chunks)} ocr={ocr_status}")
'@ | & $python @argsPrefix -

Write-Host "`n== OCR smoke test =="
@'
from pathlib import Path
from PIL import Image, ImageDraw
from bid_agent.extractors import OcrEngine
path = Path("storage/ocr_smoke.png")
path.parent.mkdir(exist_ok=True)
img = Image.new("RGB", (420, 120), "white")
draw = ImageDraw.Draw(img)
draw.text((20, 35), "SAMPLE CERT 12345", fill="black")
img.save(path)
text = OcrEngine("ch").image_to_text(path)
print(f"ocr text: {text}")
assert "12345" in text
'@ | & $python @argsPrefix -

Write-Host "`n== App health =="
Write-Host "Run scripts\run-dev.ps1, then open http://localhost:8000/health"
