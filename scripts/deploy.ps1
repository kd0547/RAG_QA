<#
.SYNOPSIS
    프로젝트를 릴리스 서버로 복사한다. (원격 저장소 없이 tar + scp/ssh)

.DESCRIPTION
    1) 이미지 빌드에 필요한 소스만 tar.gz로 묶는다. (.venv, node_modules, 실행 데이터, .env 제외)
    2) scp로 서버 홈에 올리고 ssh로 RemoteDir에 푼다.
    3) -Build 를 주면 서버에서 docker compose up -d --build 까지 실행한다.

    서버의 .env, storage/, data/ 는 덮어쓰지 않는다. (-WithData 를 주면 storage 데이터는 덮어씀)
    로컬에서 지운 파일은 서버에 남아 있으니, 필요하면 서버에서 직접 지운다.

.EXAMPLE
    .\scripts\deploy.ps1 -DryRun
    .\scripts\deploy.ps1 -Server user@14.38.199.190
    .\scripts\deploy.ps1 -Server user@14.38.199.190 -WithData -Build
#>
param(
    # ssh 접속 대상 (user@host)
    [string]$Server,
    # 서버에서 프로젝트를 둘 경로
    [string]$RemoteDir = "~/rag_QA",
    # storage/token_cache.bin, storage/chroma, storage/mail.db 도 함께 보낸다 (서버 데이터를 덮어씀)
    [switch]$WithData,
    # 복사 후 서버에서 docker compose up -d --build 실행
    [switch]$Build,
    # 압축만 하고 들어갈 내용/크기만 보여준다 (서버 접속 안 함)
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$archiveName = "rag_QA_deploy.tgz"
$archive = Join-Path $root $archiveName
$tar = Join-Path $env:SystemRoot "System32\tar.exe"

if (-not $DryRun -and -not $Server) {
    throw "-Server user@host 를 지정하세요. (내용만 확인하려면 -DryRun)"
}

# 최상위에서 통째로 빼는 항목
$topLevelExcludes = @(
    ".venv", ".git", ".idea", ".claude", "__pycache__", ".pytest_cache", ".jbeval",
    ".env", "temp", "markdown", "chroma_data", "identifier.sqlite",
    $archiveName
)

# 하위 경로 제외 패턴 (bsdtar는 경로 어디에 있든 매칭한다)
$excludes = @(
    "__pycache__", "*.pyc", "*.db-journal",
    "frontend/node_modules", "frontend/dist",   # 프론트는 Dockerfile에서 새로 빌드
    "data/uploads", "data/images", "data/*.db"
)
if (-not $WithData) {
    $excludes += @("storage/chroma", "storage/mail.db", "storage/token_cache.bin")
}

# ---------- 1. 압축 ----------
$entries = Get-ChildItem -Path $root -Force |
    Where-Object { $topLevelExcludes -notcontains $_.Name } |
    ForEach-Object { $_.Name }

$excludeArgs = $excludes | ForEach-Object { "--exclude=$_" }

Write-Host "압축 중... ($archive)"
& $tar -czf $archive @excludeArgs -C $root @entries
if ($LASTEXITCODE -ne 0) { throw "tar 압축 실패 (exit $LASTEXITCODE)" }

$sizeMb = [math]::Round((Get-Item $archive).Length / 1MB, 1)
Write-Host "압축 완료: $sizeMb MB"

if ($DryRun) {
    Write-Host "`n[DryRun] 최상위 항목: $($entries -join ', ')"
    Write-Host "[DryRun] 전체 파일 수: $((& $tar -tzf $archive | Where-Object { -not $_.EndsWith('/') }).Count)"
    Write-Host "[DryRun] storage 안 포함 파일:"
    & $tar -tzf $archive | Where-Object { $_ -like "storage/*" -and -not $_.EndsWith('/') } |
        ForEach-Object { "  $_" }
    Remove-Item $archive
    return
}

try {
    # ---------- 2. 업로드 ----------
    Write-Host "업로드 중... ($Server)"
    & scp $archive "${Server}:$archiveName"
    if ($LASTEXITCODE -ne 0) { throw "scp 업로드 실패 (exit $LASTEXITCODE)" }

    # ---------- 3. 서버에서 풀기 ----------
    # Windows bsdtar가 넣은 확장 헤더 경고는 GNU tar에서 무시한다.
    $remote = @(
        "set -e",
        "mkdir -p $RemoteDir/storage $RemoteDir/data",
        "tar --warning=no-unknown-keyword -xzf ~/$archiveName -C $RemoteDir",
        "rm -f ~/$archiveName",
        "[ -f $RemoteDir/.env ] || echo '!! $RemoteDir/.env 가 없습니다. .env.example 을 복사해 채우세요.'"
    )
    if ($Build) {
        $remote += "cd $RemoteDir && docker compose up -d --build"
    }

    Write-Host "서버에서 압축 해제$(if ($Build) { ' + 빌드' }) 중..."
    & ssh $Server ($remote -join " && ")
    if ($LASTEXITCODE -ne 0) { throw "서버 작업 실패 (exit $LASTEXITCODE)" }

    Write-Host "완료: ${Server}:$RemoteDir"
}
finally {
    Remove-Item $archive -ErrorAction SilentlyContinue
}
