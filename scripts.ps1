param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("backup", "restore")]
    [string]$Action,
    [string]$File
)

$ErrorActionPreference = "Stop"
$backupDir = Join-Path $PSScriptRoot "backups"

if ($Action -eq "backup") {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $target = "/backups/baka-$stamp.dump"
    docker compose exec -T db pg_dump -U baka -d baka -Fc -f $target
    Write-Host "Backup created: backups/baka-$stamp.dump"
    exit 0
}

if (-not $File) { throw "Restore requires -File backups/<name>.dump" }
$resolved = (Resolve-Path -LiteralPath $File).Path
if (-not $resolved.StartsWith((Resolve-Path -LiteralPath $backupDir).Path)) {
    throw "Restore file must be inside the backups directory."
}
$containerFile = "/backups/" + [IO.Path]::GetFileName($resolved)
docker compose exec -T db pg_restore -U baka -d baka --clean --if-exists $containerFile
Write-Host "Restore completed: $resolved"
