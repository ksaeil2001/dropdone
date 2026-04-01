#Requires -Version 5.1
param(
    [switch]$RebuildDist,
    [switch]$SkipSmoke,
    [string]$PythonExe = 'python',
    [string]$IsccPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path $PSScriptRoot -Parent
$IssPath = Join-Path $RepoRoot 'dropdone_setup.iss'
$BuildSpecPath = Join-Path $RepoRoot 'build.spec'
$DistExePath = Join-Path $RepoRoot 'dist\DropDone\DropDone.exe'
$ExtensionManifestPath = Join-Path $RepoRoot 'extension\manifest.json'
$NativeHostScriptPath = Join-Path $RepoRoot 'native_host\register_host.ps1'

function Resolve-IsccPath {
    param([string]$PreferredPath)

    if ($PreferredPath) {
        if (Test-Path $PreferredPath) {
            return (Resolve-Path $PreferredPath).Path
        }
        throw "Specified ISCC.exe path does not exist: $PreferredPath"
    }

    $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Get-InstallerVersion {
    $match = Select-String -Path $IssPath -Pattern '^#define MyAppVersion "([^"]+)"' | Select-Object -First 1
    if (-not $match) {
        throw "Unable to parse MyAppVersion from $IssPath"
    }
    return $match.Matches[0].Groups[1].Value
}

function Assert-FileExists {
    param(
        [string]$Path,
        [string]$Description
    )

    if (-not (Test-Path $Path)) {
        throw "$Description not found: $Path"
    }
}

function Invoke-DistBuild {
    Write-Host "[build] Running PyInstaller onedir build..."
    Push-Location $RepoRoot
    try {
        & $PythonExe -m PyInstaller build.spec --clean -y
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller build failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Invoke-InstallerSmoke {
    param([string]$InstallerPath)

    Assert-FileExists -Path $InstallerPath -Description 'Installer output'
    $item = Get-Item $InstallerPath
    if ($item.Length -lt 1MB) {
        throw "Installer output looks too small ($($item.Length) bytes): $InstallerPath"
    }

    Assert-FileExists -Path $DistExePath -Description 'Built DropDone.exe'
    Assert-FileExists -Path $ExtensionManifestPath -Description 'Extension manifest'
    Assert-FileExists -Path $NativeHostScriptPath -Description 'Native host registration script'

    Write-Host "[smoke] Installer output present: $InstallerPath ($([math]::Round($item.Length / 1MB, 2)) MB)"
}

$version = Get-InstallerVersion
$installerFileName = "DropDone_Setup_v$version.exe"
$installerPath = Join-Path $PSScriptRoot $installerFileName
$resolvedIscc = Resolve-IsccPath -PreferredPath $IsccPath

if (-not $resolvedIscc) {
    throw @"
Inno Setup Compiler (ISCC.exe) was not found.
Install it, then rerun this script.

Suggested setup:
  winget install JRSoftware.InnoSetup

Or rerun with:
  powershell -ExecutionPolicy Bypass -File .\installer\build_installer.ps1 -IsccPath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
"@
}

Assert-FileExists -Path $IssPath -Description 'Inno Setup script'
Assert-FileExists -Path $BuildSpecPath -Description 'PyInstaller spec'

if ($RebuildDist -or -not (Test-Path $DistExePath)) {
    Invoke-DistBuild
} else {
    Write-Host "[build] Reusing existing dist build: $DistExePath"
}

Write-Host "[build] Using ISCC.exe: $resolvedIscc"
& $resolvedIscc $IssPath
if ($LASTEXITCODE -ne 0) {
    throw "ISCC.exe failed with exit code $LASTEXITCODE"
}

if (-not $SkipSmoke) {
    Invoke-InstallerSmoke -InstallerPath $installerPath
}

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$statePath = Join-Path $PSScriptRoot "build_state_$timestamp.txt"
@(
    "timestamp=$timestamp"
    "version=$version"
    "iscc=$resolvedIscc"
    "dist_exe=$DistExePath"
    "installer=$installerPath"
    "smoke_skipped=$SkipSmoke"
) | Set-Content -Path $statePath -Encoding UTF8

Write-Host "[done] Installer build complete."
Write-Host "       installer : $installerPath"
Write-Host "       build log : $statePath"
