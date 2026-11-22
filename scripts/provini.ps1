# Genera i due provini vocali (Isabella ed Elsa) in output\provini.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "esegui.ps1") --provini
exit $LASTEXITCODE
