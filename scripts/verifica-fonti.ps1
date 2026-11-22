# Controlla i feed di config\fonti.yaml con richieste reali.
# Uso:  .\scripts\verifica-fonti.ps1
#       .\scripts\verifica-fonti.ps1 --strict
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
    Write-Error "Manca .venv. Esegui prima .\scripts\installa.ps1"
    exit 1
}
& $python -m notiziario.verifica_fonti @Argomenti
exit $LASTEXITCODE
