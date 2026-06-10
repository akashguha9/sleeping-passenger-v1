# S4-A5: start the advisory MVP from the isolated venv (loopback bind).
# The server boot path itself re-enforces isolation (enforce_isolation_or_die)
# and refuses a global interpreter unless MVP_ALLOW_GLOBAL_PYTHON=1.
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo
& $PSScriptRoot\check_runtime_isolation.ps1
& .\.venv\Scripts\python.exe scripts\api_server.py
