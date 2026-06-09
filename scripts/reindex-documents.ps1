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

$code = @'
from bid_agent import db
from bid_agent.config import get_settings
from bid_agent.document_service import reextract_document

settings = get_settings()
db.init_db(settings.database_path)

with db.db_session(settings.database_path) as conn:
    docs = db.list_documents(conn, limit=10000)
    for doc in docs:
        print(f"reextract document {doc['id']}: {doc['title']}")
        try:
            reextract_document(conn, settings=settings, document_id=int(doc["id"]))
            refreshed = db.get_document(conn, int(doc["id"]))
            chunk_count = len(db.list_document_chunks(conn, int(doc["id"]), limit=100000))
            print(f"  ok extraction={refreshed['extraction_status']} ocr={refreshed['ocr_status']} chunks={chunk_count}")
        except Exception as exc:
            print(f"  failed {exc}")
'@

$code | & $python @argsPrefix -
