@echo off
setlocal
rem Prefer PowerShell 7 when available; otherwise use Windows PowerShell.
set "DOWNTIME_POWERSHELL=pwsh.exe"
where pwsh.exe >nul 2>&1
if errorlevel 1 set "DOWNTIME_POWERSHELL=powershell.exe"
where %DOWNTIME_POWERSHELL% >nul 2>&1
if errorlevel 1 (
    echo PowerShell 5.1 or newer is required. Install PowerShell and add it to PATH. 1>&2
    exit /b 1
)
%DOWNTIME_POWERSHELL% -NoLogo -NoProfile -Command "if ($PSVersionTable.PSVersion -lt [version]'5.1') { exit 1 }"
if errorlevel 1 (
    echo PowerShell 5.1 or newer is required. Update PowerShell before starting the app. 1>&2
    exit /b 1
)
rem Bypass policy only for this process so the local launcher can run.
%DOWNTIME_POWERSHELL% -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "DOWNTIME_EXIT_CODE=%ERRORLEVEL%"
exit /b %DOWNTIME_EXIT_CODE%
