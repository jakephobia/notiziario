# Importa una lista OPML, TXT, CSV o JSON.
# Uso: .\scripts\importa-feed.ps1 .\mia-lista.opml
#       .\scripts\importa-feed.ps1 .\mia-lista.json --attiva-tutte
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $File,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Argomenti
)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "esegui.ps1") --importa-feed $File @Argomenti
exit $LASTEXITCODE
