# Esegue il Notiziario con il Python del venv locale.
# Esempi:
#   .\scripts\esegui.ps1
#   .\scripts\esegui.ps1 --durata svelto
#   .\scripts\esegui.ps1 --dry-run
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Argomenti
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUTF8 = "1"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Manca .venv. Esegui prima: powershell -ExecutionPolicy Bypass -File .\scripts\installa.ps1"
    exit 1
}

& $python "main.py" @Argomenti
exit $LASTEXITCODE
