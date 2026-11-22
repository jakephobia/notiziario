# Prepara l'ambiente locale del Notiziario.
# Uso:  powershell -ExecutionPolicy Bypass -File .\scripts\installa.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUTF8 = "1"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Output "Creo il venv .venv..."
    python -m venv .venv
} else {
    Write-Output "Il venv .venv esiste già."
}

Write-Output "Installo le dipendenze..."
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
Write-Output "Fatto. Ora puoi usare: powershell -ExecutionPolicy Bypass -File .\scripts\esegui.ps1"
