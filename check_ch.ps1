$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

python scripts/inspect_clickhouse.py @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
