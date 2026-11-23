[CmdletBinding()]
param(
    [string]$Notes = "",
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
$Repo = "LupesHk/LDesktop"
$Branch = "main"
$Root = $PSScriptRoot
Set-Location $Root

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        $argumentText = $Arguments -join ' '
        $message = "O comando $File $argumentText terminou com código $LASTEXITCODE."
        throw $message
    }
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

$configPath = Join-Path $Root "src\core\update_config.py"
$issPath = Join-Path $Root "LDesktop.iss"
$manifestPath = Join-Path $Root "updates\stable.json"
$specPath = Join-Path $Root "LDesktop.spec"
$updaterPath = Join-Path $Root "src\updater_main.py"
$installerDir = Join-Path $Root "dist\installer"

foreach ($required in @($configPath, $issPath, $manifestPath, $specPath, $updaterPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Arquivo obrigatório não encontrado: $required"
    }
}

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw "Python não encontrado. Crie/ative o ambiente virtual do projeto." }
    $python = $pythonCommand.Source
}

$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCommand) { throw "Git não encontrado no PATH." }
$git = $gitCommand.Source

$ghCommand = Get-Command gh -ErrorAction SilentlyContinue
if ($ghCommand) {
    $gh = $ghCommand.Source
} else {
    $ghFallback = Join-Path ${env:ProgramFiles} "GitHub CLI\gh.exe"
    if (-not (Test-Path -LiteralPath $ghFallback)) { throw "GitHub CLI (gh) não encontrado. Instale-o ou adicione-o ao PATH." }
    $gh = $ghFallback
}

$iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
if (-not (Test-Path -LiteralPath $iscc -PathType Leaf)) {
    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if (-not $isccCommand) { throw "Inno Setup 6 (ISCC.exe) não encontrado." }
    $iscc = $isccCommand.Source
}

Write-Host "`n=== VERIFICAÇÕES INICIAIS ===" -ForegroundColor Cyan
$branch = (& $git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw "Não foi possível identificar a branch atual." }
if ($branch -ne $Branch) { throw "A branch atual é '$branch'. Troque para '$Branch' antes de publicar." }

# Permite apenas estes dois resíduos conhecidos; eles nunca são adicionados ao commit.
$allowedUntracked = @("?? LDesktopUpdater.spec", "?? src/core/app.py.backup")
$statusLines = @(& $git status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0) { throw "Não foi possível consultar o status do Git." }
$unexpected = @($statusLines | Where-Object { $_ -notin $allowedUntracked })
if ($unexpected.Count -gt 0) {
    Write-Host "O repositório tem alterações pendentes:" -ForegroundColor Yellow
    $unexpected | ForEach-Object { Write-Host "  $_" }
    throw "Faça commit ou descarte conscientemente essas alterações antes de iniciar a publicação. O script não fará commit de código automaticamente."
}

$authOutput = & $gh auth status --hostname github.com 2>&1
if ($LASTEXITCODE -ne 0) { $authOutput | ForEach-Object { Write-Host $_ }; throw "GitHub CLI não está autenticado. Execute 'gh auth login'." }

$configOriginal = [System.IO.File]::ReadAllText($configPath)
$issOriginal = [System.IO.File]::ReadAllText($issPath)
$versionMatch = [regex]::Match($configOriginal, '(?m)^\s*APP_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"')
if (-not $versionMatch.Success) { throw "Não foi possível ler APP_VERSION em src/core/update_config.py." }

$currentVersion = "{0}.{1}.{2}" -f $versionMatch.Groups[1].Value, $versionMatch.Groups[2].Value, $versionMatch.Groups[3].Value
$issVersionMatch = [regex]::Match($issOriginal, '(?m)^\s*#define\s+MyAppVersion\s+"([^"]+)"')