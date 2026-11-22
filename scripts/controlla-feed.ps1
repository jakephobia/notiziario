# Controlla testo, paywall, podcast e inattività dei feed.
# Uso: .\scripts\controlla-feed.ps1
#       .\scripts\controlla-feed.ps1 --disattiva-non-ok
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Argomenti
)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "esegui.ps1") --controlla-feed @Argomenti
exit $LASTEXITCODE
