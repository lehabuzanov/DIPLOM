param(
    [Parameter(Mandatory = $true)]
    [string]$BackupDir,
    [string]$ComposeFile = "docker-compose.yml",
    [switch]$Yes
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

$dbFile = Join-Path $BackupDir "sem_corpus_db.dump"
$mediaFile = Join-Path $BackupDir "sem_corpus_media.tar.gz"

if (-not (Test-Path $dbFile)) {
    throw "Database dump not found: $dbFile"
}
if (-not (Test-Path $mediaFile)) {
    throw "Media archive not found: $mediaFile"
}

if (-not $Yes) {
    $answer = Read-Host "This will replace database contents and media files. Type RESTORE to continue"
    if ($answer -ne "RESTORE") {
        Write-Host "Restore cancelled."
        exit 1
    }
}

$dbContainer = Get-RequiredContainerId -ServiceName "db"
$webContainer = Get-RequiredContainerId -ServiceName "web"

Write-Host "Restoring PostgreSQL database from: $dbFile"
docker cp $dbFile "${dbContainer}:/tmp/sem_corpus_db.dump"
docker compose -f $ComposeFile exec -T db pg_restore -U sem_corpus -d sem_corpus --clean --if-exists --no-owner --no-acl /tmp/sem_corpus_db.dump
docker compose -f $ComposeFile exec -T db rm -f /tmp/sem_corpus_db.dump

Write-Host "Restoring media files from: $mediaFile"
docker cp $mediaFile "${webContainer}:/tmp/sem_corpus_media.tar.gz"
docker compose -f $ComposeFile exec -T web sh -c "rm -rf /app/media/* && tar -C /app -xzf /tmp/sem_corpus_media.tar.gz && rm -f /tmp/sem_corpus_media.tar.gz"

Write-Host "Restore completed from: $BackupDir"
