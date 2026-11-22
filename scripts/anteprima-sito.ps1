# Avvia un server locale per vedere docs\index.html e il player.
# Apri poi http://localhost:8000/docs/
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Manca .venv. Esegui prima .\scripts\installa.ps1"
    exit 1
}
Start-Process "http://localhost:8000/docs/"
& $python -m http.server 8000
