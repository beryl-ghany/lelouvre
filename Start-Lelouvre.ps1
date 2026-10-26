param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$workspace = $PSScriptRoot
$address = 'http://127.0.0.1:8765'
$expectedModel = if ($env:LELOUVRE_GEMMA_MODEL) { $env:LELOUVRE_GEMMA_MODEL } elseif ($env:LELOUVRE_OLLAMA_MODEL) { $env:LELOUVRE_OLLAMA_MODEL } else { 'gemma4:e2b' }

function Test-Lelouvre {
    try {
        $response = Invoke-RestMethod -Uri "$address/api/state" -TimeoutSec 2
        return ($response.name -eq 'Lelouvre') -and ($response.version -eq '0.5.2') -and ($response.capabilities.internship_agent -eq $true) -and ($response.capabilities.demo_mode -eq ($env:LELOUVRE_DEMO -eq '1')) -and ($response.capabilities.gemma.model -eq $expectedModel)
    } catch { return $false }
}

if (-not (Test-Lelouvre)) {
    $existing = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existing) {
        $runningService = Get-CimInstance Win32_Process -Filter "ProcessId=$($existing.OwningProcess)"
        if ($runningService.CommandLine -notmatch 'lelouvre[.]server') {
            throw 'Port 8765 is being used by another app. Close it or use a different port.'
        }
        Stop-Process -Id $existing.OwningProcess -ErrorAction Stop
        Start-Sleep -Seconds 1
    }
    if (-not $env:LELOUVRE_AUTO_APPLY) { $env:LELOUVRE_AUTO_APPLY = '1' }
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $projectPython = Join-Path $workspace '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $projectPython) {
        $pythonExecutable = $projectPython
    } elseif (Test-Path -LiteralPath $bundledPython) {
        $pythonExecutable = $bundledPython
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCommand) { throw 'Python 3.10 or newer is needed to start Lelouvre. Install Python, then try again.' }
        $pythonExecutable = $pythonCommand.Source
    }
    $dataDirectory = Join-Path $workspace 'data'
    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
    $serviceProcess = Start-Process -FilePath $pythonExecutable -ArgumentList @('-m','lelouvre.server','--port','8765') `
        -WorkingDirectory $workspace -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $dataDirectory 'server.out.log') `
        -RedirectStandardError (Join-Path $dataDirectory 'server.err.log')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-Lelouvre) { break }
        $serviceProcess.Refresh()
        if ($serviceProcess.HasExited) { throw "Lelouvre could not start. See data\server.err.log in $workspace." }
        Start-Sleep -Milliseconds 300
    }
    if (-not (Test-Lelouvre)) { throw "Lelouvre has not responded yet. See data\server.err.log in $workspace." }
}
Write-Output "Lelouvre is ready: $address"
if (-not $NoBrowser) { Start-Process "$address/#today" }
