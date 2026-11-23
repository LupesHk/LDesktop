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
if (-not $issVersionMatch.Success) {
    throw "Não foi possível localizar MyAppVersion em LDesktop.iss."
}

if ($issVersionMatch.Groups[1].Value -ne $currentVersion) {
    throw "As versões de Python e Inno Setup estão divergentes."
}

$major = [int]$versionMatch.Groups[1].Value
$minor = [int]$versionMatch.Groups[2].Value
$patch = [int]$versionMatch.Groups[3].Value + 1

$newVersion = "$major.$minor.$patch"
$tag = "v$newVersion"

$localTag = @(& $git tag --list $tag)
if ($localTag.Count -gt 0) {
    throw "A tag local $tag já existe."
}

$remoteTag = @(& $git ls-remote --tags origin "refs/tags/$tag")
if ($LASTEXITCODE -ne 0) {
    throw "Não foi possível consultar as tags remotas."
}
if ($remoteTag.Count -gt 0) {
    throw "A tag remota $tag já existe."
}

if ($PreflightOnly) {
    Write-Host "`nPRE-VERIFICACAO CONCLUIDA" -ForegroundColor Green
    Write-Host "Versao atual: $currentVersion"
    Write-Host "Proxima versao: $newVersion"
    Write-Host "Nenhum arquivo foi alterado e nada foi publicado."
    return
}

if ([string]::IsNullOrWhiteSpace($Notes)) {
    $Notes = Read-Host "Notas da versao"
}

if ([string]::IsNullOrWhiteSpace($Notes)) {
    $Notes = "Melhorias e correcoes de estabilidade."
}

Write-Host "`nVersao atual: $currentVersion"
Write-Host "Nova versao: $newVersion"
Write-Host "Notas: $Notes"

$sourceCommitCreated = $false
$releaseCreated = $false

try {
    $configUpdated = [regex]::Replace(
        $configOriginal,
        '(?m)^(\s*APP_VERSION\s*=\s*)"\d+\.\d+\.\d+"',
        ('${1}"' + $newVersion + '"')
    )

    $issUpdated = [regex]::Replace(
        $issOriginal,
        '(?m)^(\s*#define\s+MyAppVersion\s+)"[^"]+"',
        ('${1}"' + $newVersion + '"')
    )

    if ($configUpdated -eq $configOriginal -or $issUpdated -eq $issOriginal) {
        throw "Nao foi possivel atualizar as versoes."
    }

    Write-Utf8NoBom $configPath $configUpdated
    Write-Utf8NoBom $issPath $issUpdated

    Write-Host "`n=== VALIDANDO PYTHON ===" -ForegroundColor Cyan
    Invoke-Checked $python @("-m", "compileall", "-q", "src")

    Write-Host "`n=== COMPILANDO APLICATIVO ===" -ForegroundColor Cyan
    Invoke-Checked $python @("-m", "PyInstaller", "--clean", "--noconfirm", ".\LDesktop.spec")

    if (-not (Test-Path ".\dist\LDesktop\LDesktop.exe")) {
        throw "Executavel principal nao encontrado."
    }

    Write-Host "`n=== COMPILANDO ATUALIZADOR ===" -ForegroundColor Cyan
    Invoke-Checked $python @(
        "-m", "PyInstaller", "--clean", "--noconfirm",
        "--onefile", "--noconsole",
        "--name", "LDesktopUpdater",
        "--distpath", "dist\updater",
        "--workpath", "build\updater",
        ".\src\updater_main.py"
    )

    if (-not (Test-Path ".\dist\updater\LDesktopUpdater.exe")) {
        throw "Executavel do atualizador nao encontrado."
    }

    Write-Host "`n=== GERANDO INSTALADOR ===" -ForegroundColor Cyan
    Invoke-Checked $iscc @(".\LDesktop.iss")

    $installer = Join-Path $installerDir "LDesktop-Setup-$newVersion.exe"

    if (-not (Test-Path -LiteralPath $installer)) {
        throw "Instalador nao encontrado: $installer"
    }

    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToUpperInvariant()
    $sizeMB = [math]::Round((Get-Item $installer).Length / 1MB, 2)

    Write-Host "`n=== RESUMO ===" -ForegroundColor Cyan
    Write-Host "Versao: $newVersion"
    Write-Host "Instalador: $installer"
    Write-Host "Tamanho: $sizeMB MiB"
    Write-Host "SHA256: $hash"
    Write-Host "Notas: $Notes"

    $confirmation = Read-Host "Digite PUBLICAR para confirmar"

    if ($confirmation -cne "PUBLICAR") {
        Write-Utf8NoBom $configPath $configOriginal
        Write-Utf8NoBom $issPath $issOriginal
        Write-Host "Publicacao cancelada. Versoes restauradas." -ForegroundColor Yellow
        return
    }

    Write-Host "`n=== COMMIT DA VERSAO ===" -ForegroundColor Cyan

    Invoke-Checked $git @("add", "src/core/update_config.py", "LDesktop.iss")
    Invoke-Checked $git @("diff", "--cached", "--check")
    Invoke-Checked $git @("commit", "-m", "Prepare release $tag")

    $sourceCommitCreated = $true

    Invoke-Checked $git @("push", "origin", $Branch)

    Write-Host "`n=== PUBLICANDO NO GITHUB ===" -ForegroundColor Cyan

    Invoke-Checked $gh @(
        "release", "create", $tag, $installer,
        "--repo", $Repo,
        "--target", $Branch,
        "--title", "L Desktop $newVersion",
        "--notes", $Notes
    )

    $releaseCreated = $true

    Write-Host "`n=== ATUALIZANDO MANIFESTO ===" -ForegroundColor Cyan

    $manifest = [ordered]@{
        version = $newVersion
        download_url = "https://github.com/$Repo/releases/download/$tag/LDesktop-Setup-$newVersion.exe"
        sha256 = $hash
        notes = $Notes
    }

    $manifestJson = ($manifest | ConvertTo-Json -Depth 3) + "`n"

    Write-Utf8NoBom $manifestPath $manifestJson

    Invoke-Checked $git @("add", "updates/stable.json")
    Invoke-Checked $git @("diff", "--cached", "--check")
    Invoke-Checked $git @("commit", "-m", "Update stable manifest to $tag")
    Invoke-Checked $git @("push", "origin", $Branch)

    Write-Host "`nPUBLICACAO CONCLUIDA!" -ForegroundColor Green
    Write-Host "https://github.com/$Repo/releases/tag/$tag"
}
catch {
    if (-not $sourceCommitCreated) {
        & $git restore --staged -- "src/core/update_config.py" "LDesktop.iss" 2>$null
        Write-Utf8NoBom $configPath $configOriginal
        Write-Utf8NoBom $issPath $issOriginal
        Write-Warning "Arquivos de versao restaurados."
    }
    elseif (-not $releaseCreated) {
        Write-Warning "Commit criado. Confira o GitHub antes de tentar novamente."
    }
    else {
        Write-Warning "Release criada. Confira o manifesto e seu envio ao GitHub."
    }

    throw
}