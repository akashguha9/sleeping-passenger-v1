# S4-A5: create the isolated runtime venv from the pinned lockfile.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\windows\bootstrap_venv.ps1
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo

$py = $null
foreach ($candidate in @("py -3.13", "py -3", "python")) {
    try {
        $v = Invoke-Expression "$candidate --version" 2>$null
        if ($v) { $py = $candidate; break }
    } catch {}
}
if (-not $py) { throw "No Python interpreter found on PATH." }
Write-Host "Using interpreter: $py ($((Invoke-Expression "$py --version")))"

if (-not (Test-Path ".venv")) {
    Invoke-Expression "$py -m venv .venv"
    Write-Host "Created .venv"
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
# Pinned lockfile ONLY — never the floating ranges.
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed — dependency conflict in the venv." }
& .\.venv\Scripts\python.exe -m pip install pip-audit
& .\.venv\Scripts\python.exe -m pip_audit -r requirements.lock --strict
if ($LASTEXITCODE -ne 0) { throw "pip-audit found vulnerabilities in requirements.lock." }
Write-Host "venv bootstrap complete and audited."
