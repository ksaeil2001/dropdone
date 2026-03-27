#Requires -Version 5.1
<#
.SYNOPSIS
    DropDone Chrome Native Messaging 호스트를 Windows 레지스트리에 등록합니다.
.DESCRIPTION
    - dropdone_host_run.bat (Python 런처) 생성
    - dropdone_host.json 의 "path" 필드를 절대 경로로 업데이트
    - HKCU\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host 등록
.NOTES
    관리자 권한 불필요 (HKCU 사용)
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── 1. 경로 계산 ─────────────────────────────────────────────────────────────
$HostDir  = $PSScriptRoot
$Launcher = Join-Path $HostDir 'dropdone_host_run.bat'
$JsonPath = Join-Path $HostDir 'dropdone_host.json'
$RegKey   = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host'

Write-Host "[DropDone] Native Messaging 호스트 등록 시작..." -ForegroundColor Cyan

# ── 2. Python 런처 bat 생성 ──────────────────────────────────────────────────
$LauncherContent = "@echo off`r`npython `"$HostDir\dropdone_host.py`"`r`n"
[System.IO.File]::WriteAllText($Launcher, $LauncherContent, [System.Text.Encoding]::ASCII)
Write-Host "[OK] 런처 생성: $Launcher" -ForegroundColor Green

# ── 3. dropdone_host.json path 필드 업데이트 ─────────────────────────────────
$Json       = Get-Content -Raw $JsonPath | ConvertFrom-Json
$Json.path  = $Launcher
$JsonOutput = $Json | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($JsonPath, $JsonOutput, [System.Text.Encoding]::UTF8)
Write-Host "[OK] JSON 업데이트: $JsonPath" -ForegroundColor Green

# ── 4. 레지스트리 등록 ───────────────────────────────────────────────────────
# Chrome은 키의 기본값(unnamed, /ve)에서 JSON 경로를 읽습니다.
# PowerShell의 Set-ItemProperty 로는 기본값 설정이 불안정하므로 reg.exe 사용.
$RegKeyPlain = 'HKCU\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host'
$Result = reg add $RegKeyPlain /ve /t REG_SZ /d $JsonPath /f 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "레지스트리 등록 실패: $Result"
    exit 1
}
Write-Host "[OK] 레지스트리 등록: $RegKeyPlain" -ForegroundColor Green

# ── 5. 등록 결과 검증 ────────────────────────────────────────────────────────
$Registered = (Get-ItemProperty -Path $RegKey).'(default)'
if ($Registered -ne $JsonPath) {
    Write-Error "레지스트리 값 검증 실패.`n  예상: $JsonPath`n  실제: $Registered"
    exit 1
}

# ── 6. 완료 메시지 ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "────────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host " 등록 완료! Chrome을 재시작하면 적용됩니다." -ForegroundColor Yellow
Write-Host ""
Write-Host " 등록된 경로: $JsonPath"
Write-Host ""
Write-Host " ※ Chrome Web Store 심사 완료 후 Extension ID를"
Write-Host "   dropdone_host.json 의 allowed_origins 에 입력하세요."
Write-Host "────────────────────────────────────────────────────" -ForegroundColor Cyan
