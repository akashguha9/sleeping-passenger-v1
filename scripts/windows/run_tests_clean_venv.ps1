# S4-A5: run the full backend suite inside the isolated venv.
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo
& $PSScriptRoot\check_runtime_isolation.ps1
& .\.venv\Scripts\python.exe -m pytest -q
exit $LASTEXITCODE
