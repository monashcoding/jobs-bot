# Dev launcher -- spins up a local Postgres if DATABASE_URL is not set in .env.
$ErrorActionPreference = 'Stop'

$hasDbUrl = Test-Path .env && (Select-String -Path .env -Pattern '^DATABASE_URL=' -Quiet)

if ($hasDbUrl) {
    docker compose up -d @args
} else {
    docker compose --profile local-db up -d @args
}
