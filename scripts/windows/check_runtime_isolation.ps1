# S4-A5: verify the venv interpreter is isolated and lock-pinned.
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw ".venv missing — run scripts\windows\bootstrap_venv.ps1 first."
}
& .\.venv\Scripts\python.exe -c @"
import json, sys
sys.path.insert(0, '.')
from scripts.runtime_isolation import check_runtime_isolation
status = check_runtime_isolation()
print(json.dumps(status, indent=2))
if not status['runtime_isolated']:
    raise SystemExit('FAIL: interpreter is not venv-isolated')
print('PASS: runtime is venv-isolated; lock hash', (status['dependency_lock_hash'] or 'MISSING')[:16])
"@
if ($LASTEXITCODE -ne 0) { throw "runtime isolation check FAILED." }
