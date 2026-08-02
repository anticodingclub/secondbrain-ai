<#
.SYNOPSIS
    Task runner for Windows, mirroring the Makefile targets.

.EXAMPLE
    ./scripts/tasks.ps1 setup
    ./scripts/tasks.ps1 test
    ./scripts/tasks.ps1 migration -Message "add chat tables"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('setup', 'dev-backend', 'dev-frontend', 'test', 'lint', 'fmt',
                 'typecheck', 'migrate', 'migration', 'check', 'clean')]
    [string]$Task,

    [string]$Message = 'migration'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$Py = Join-Path $Backend '.venv\Scripts\python.exe'

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

function Assert-Venv {
    if (-not (Test-Path $Py)) {
        throw "Virtual environment not found. Run: ./scripts/tasks.ps1 setup"
    }
}

switch ($Task) {
    'setup' {
        Invoke-Step 'create venv' { py -3.11 -m venv (Join-Path $Backend '.venv') }
        Invoke-Step 'upgrade pip' { & $Py -m pip install --upgrade pip --quiet }
        Invoke-Step 'install backend' { & $Py -m pip install -e "$Backend[dev,embeddings-fast]" }
        Push-Location $Backend
        try { Invoke-Step 'apply migrations' { & $Py -m alembic upgrade head } }
        finally { Pop-Location }
        Invoke-Step 'install frontend' { npm --prefix $Frontend install }
        Write-Host "`nSetup complete. Start with: ./scripts/tasks.ps1 dev-backend" -ForegroundColor Green
    }
    'dev-backend' {
        Assert-Venv
        Push-Location $Backend
        try { & $Py -m uvicorn app.main:create_app --factory --reload --port 8000 }
        finally { Pop-Location }
    }
    'dev-frontend' { npm --prefix $Frontend run dev }
    'test' {
        Assert-Venv
        Push-Location $Backend
        try { Invoke-Step 'pytest' { & $Py -m pytest } } finally { Pop-Location }
    }
    'lint' {
        Assert-Venv
        Push-Location $Backend
        try { Invoke-Step 'ruff check' { & $Py -m ruff check app tests } }
        finally { Pop-Location }
        Invoke-Step 'eslint' { npm --prefix $Frontend run lint }
    }
    'fmt' {
        Assert-Venv
        Push-Location $Backend
        try {
            Invoke-Step 'ruff format' { & $Py -m ruff format app tests alembic }
            Invoke-Step 'ruff fix' { & $Py -m ruff check --fix app tests }
        } finally { Pop-Location }
    }
    'typecheck' {
        Assert-Venv
        Push-Location $Backend
        try { Invoke-Step 'mypy' { & $Py -m mypy app } } finally { Pop-Location }
        Invoke-Step 'tsc' { npm --prefix $Frontend exec tsc -- --noEmit }
    }
    'migrate' {
        Assert-Venv
        Push-Location $Backend
        try { Invoke-Step 'alembic upgrade' { & $Py -m alembic upgrade head } }
        finally { Pop-Location }
    }
    'migration' {
        Assert-Venv
        Push-Location $Backend
        try { Invoke-Step 'alembic revision' { & $Py -m alembic revision --autogenerate -m $Message } }
        finally { Pop-Location }
    }
    'check' {
        & $PSCommandPath lint
        & $PSCommandPath typecheck
        & $PSCommandPath test
    }
    'clean' {
        foreach ($path in @(
            "$Backend\.pytest_cache", "$Backend\.ruff_cache", "$Backend\.mypy_cache",
            "$Frontend\.next"
        )) {
            if (Test-Path $path) { Remove-Item -Recurse -Force $path }
        }
        Write-Host 'Cleaned.' -ForegroundColor Green
    }
}
