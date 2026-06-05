# AutoLux — Setup & Run
#
# Usage:
#   .\start.ps1           → installe + lance le dimmer en avant-plan
#   .\start.ps1 -Install  → installe + enregistre la tâche planifiée au démarrage
#   .\start.ps1 -Setup    → installe uniquement (venv + dépendances)

param(
    [switch]$Install,
    [switch]$Setup
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

function Write-Step([string]$Msg) {
    Write-Host "`n→ $Msg" -ForegroundColor Cyan
}

function Assert-EnvFile {
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) {
        Write-Host "`n[ERREUR] Fichier .env introuvable : $envFile" -ForegroundColor Red
        Write-Host "Copie .env.example vers .env et remplis les valeurs." -ForegroundColor Yellow
        exit 1
    }
}

function Install-Venv {
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Step "Création du venv Python..."
        python -m venv (Join-Path $Root ".venv")
    } else {
        Write-Step "Venv déjà présent, skip."
    }

    Write-Step "Installation des dépendances..."
    & (Join-Path $Root ".venv\Scripts\pip.exe") install -r (Join-Path $Root "requirements.txt") --quiet
    Write-Host "  ✓ Dépendances installées." -ForegroundColor Green
}

function Register-StartupTask {
    $ps1 = Join-Path $Root "install_startup_task.ps1"
    $vbs = Join-Path $Root "run_hidden.vbs"
    Write-Step "Enregistrement de la tâche planifiée (admin requis)..."
    Start-Process powershell -Verb RunAs -ArgumentList `
        "-NoProfile -ExecutionPolicy Bypass -File `"$ps1`" -ScriptPath `"$vbs`""
    Write-Host "  ✓ Tâche planifiée enregistrée (LumiereDimmerStartup)." -ForegroundColor Green
}

Assert-EnvFile

if ($Setup) {
    Install-Venv
    Write-Host "`n✓ Setup terminé." -ForegroundColor Green
    exit 0
}

if ($Install) {
    Install-Venv
    Register-StartupTask
    Write-Host "`n✓ Installation terminée. Le dimmer démarrera automatiquement à la prochaine connexion." -ForegroundColor Green
    exit 0
}

Install-Venv
Write-Step "Lancement du dimmer..."
& (Join-Path $Root ".venv\Scripts\python.exe") (Join-Path $Root "dimmer.py")
