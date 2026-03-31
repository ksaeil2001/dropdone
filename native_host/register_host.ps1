#Requires -Version 5.1
param(
    [string]$ExtensionId = 'aanekpdighliaaaekihmhnapnbdoiacl'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HostDir = $PSScriptRoot
$RootDir = Split-Path $HostDir -Parent
$JsonPath = Join-Path $HostDir 'dropdone_host.json'
$Launcher = Join-Path $HostDir 'dropdone_host_run.bat'
$HostPy = Join-Path $HostDir 'dropdone_host.py'
$InstalledExe = Join-Path (Join-Path $RootDir 'DropDone') 'DropDone.exe'
$BuiltExe = Join-Path (Join-Path $RootDir 'dist\DropDone') 'DropDone.exe'
$RegKey = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host'
$RegKeyPlain = 'HKCU\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host'

function Write-Launcher {
    if (Test-Path $InstalledExe) {
        $launcherContent = "@echo off`r`n`"$InstalledExe`" --native-host`r`n"
        [System.IO.File]::WriteAllText($Launcher, $launcherContent, [System.Text.Encoding]::ASCII)
        return
    }
    if (Test-Path $BuiltExe) {
        $launcherContent = "@echo off`r`n`"$BuiltExe`" --native-host`r`n"
        [System.IO.File]::WriteAllText($Launcher, $launcherContent, [System.Text.Encoding]::ASCII)
        return
    }

    $launcherContent = "@echo off`r`npython `"$HostPy`"`r`n"
    [System.IO.File]::WriteAllText($Launcher, $launcherContent, [System.Text.Encoding]::ASCII)
}

Write-Launcher
$Json = Get-Content -Raw $JsonPath | ConvertFrom-Json
$Json.path = $Launcher
$Json.allowed_origins = @("chrome-extension://$ExtensionId/")
$JsonOutput = $Json | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($JsonPath, $JsonOutput, [System.Text.Encoding]::UTF8)

$Result = reg add $RegKeyPlain /ve /t REG_SZ /d $JsonPath /f 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "레지스트리 등록 실패: $Result"
    exit 1
}

$Registered = (Get-ItemProperty -Path $RegKey).'(default)'
if ($Registered -ne $JsonPath) {
    Write-Error "레지스트리 값 검증 실패.`n  예상: $JsonPath`n  실제: $Registered"
    exit 1
}

Write-Host "[DropDone] Native Messaging 호스트 등록 완료"
Write-Host "  host path   : $Launcher"
Write-Host "  extension id: $ExtensionId"
