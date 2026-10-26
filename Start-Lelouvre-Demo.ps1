param([switch]$NoBrowser)
$env:LELOUVRE_DEMO = '1'
if (-not $env:LELOUVRE_DATABASE) {
    $env:LELOUVRE_DATABASE = Join-Path $PSScriptRoot 'data\lelouvre-demo.sqlite3'
}
& (Join-Path $PSScriptRoot 'Start-Lelouvre.ps1') @PSBoundParameters
