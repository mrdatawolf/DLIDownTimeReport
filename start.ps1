# Requires PowerShell 5.1 or newer. All arguments are forwarded to app.py.
#requires -Version 5.1
$ErrorActionPreference = 'Stop'
$appArguments = $args
$exitCode = 1

Push-Location -LiteralPath $PSScriptRoot
try {
    $versionFile = Join-Path $PSScriptRoot 'VERSION.txt'
    $version = ''
    if (Test-Path -LiteralPath $versionFile) { $version = ([string](Get-Content -LiteralPath $versionFile -Raw)).Trim() }
    if (-not $version) { $version = 'unknown' }
    Write-Host "Downtime Tracker version $version"
    $pythonCommand = $null
    $pythonPrefix = @()
    foreach ($candidate in @('py', 'python', 'python3')) {
        $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { continue }
        $prefix = @()
        if ($candidate -eq 'py') { $prefix = @('-3') }
        try {
            & $command.Source @prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null | Out-Null
        }
        catch { continue }
        if ($LASTEXITCODE -eq 0) {
            $pythonCommand = $command.Source
            $pythonPrefix = $prefix
            break
        }
    }
    if (-not $pythonCommand) {
        throw 'Python 3.10 or newer is required. Install Python with the launcher or add it to PATH.'
    }
    if (-not (Get-Command pdftotext -CommandType Application -ErrorAction SilentlyContinue)) {
        throw 'pdftotext is required. Install Poppler for Windows and add its bin or Library\bin directory to PATH.'
    }
    Write-Host 'Starting Downtime Tracker...'
    & $pythonCommand @pythonPrefix (Join-Path $PSScriptRoot 'app.py') @appArguments
    $exitCode = $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
}
finally {
    Pop-Location
}
exit $exitCode
