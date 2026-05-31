param(
    [string]$OutputDir = "backups",
    [string]$ComposeFile = "docker-compose.yml"
)

$ErrorActionPreference = "Stop"

function Get-RequiredContainerId {
    param([string]$ServiceName)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $containerId = (& docker compose -f $ComposeFile ps -q $ServiceName 2>$null | Out-String).Trim()
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "Could not query Docker Compose. Check that Docker is running and this shell has access to it."
    }
    if (-not $containerId) {
        throw "Container for service '$ServiceName' is not running."
    }
    return $containerId
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $OutputDir $timestamp
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

$dbFile = Join-Path $backupRoot "sem_corpus_db.dump"
$mediaFile = Join-Path $backupRoot "sem_corpus_media.tar.gz"
$manifestFile = Join-Path $backupRoot "manifest.txt"
$dbContainer = Get-RequiredContainerId -ServiceName "db"
$webContainer = Get-RequiredContainerId -ServiceName "web"

Write-Host "Creating PostgreSQL backup: $dbFile"
docker compose -f $ComposeFile exec -T db pg_dump -U sem_corpus -d sem_corpus -Fc --no-owner --no-acl -f /tmp/sem_corpus_db.dump
docker cp "${dbContainer}:/tmp/sem_corpus_db.dump" $dbFile
docker compose -f $ComposeFile exec -T db rm -f /tmp/sem_corpus_db.dump

Write-Host "Creating media backup: $mediaFile"
docker compose -f $ComposeFile exec -T web tar -C /app -czf /tmp/sem_corpus_media.tar.gz media
docker cp "${webContainer}:/tmp/sem_corpus_media.tar.gz" $mediaFile
docker compose -f $ComposeFile exec -T web rm -f /tmp/sem_corpus_media.tar.gz

@(
    "created_at=$((Get-Date).ToString("s"))"
    "compose_file=$ComposeFile"
    "database_dump=sem_corpus_db.dump"
    "media_archive=sem_corpus_media.tar.gz"
) | Set-Content -Encoding UTF8 -Path $manifestFile

Write-Host "Backup completed: $backupRoot"
