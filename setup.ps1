# One-shot Windows setup for agent-to-apply. Safe to re-run (every step checks first).
#
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Minimal   (Python + project only: what Start.bat runs)
#
# Costs zero LLM requests. Installs: Git, Python, Node (via winget, only if missing), Claude Code,
# the project venv, and wires Claude Code to OpenRouter. The automation browser is BrowserOS neo
# (install it yourself); Chrome is offered only as a fallback.
# ASCII only on purpose: Windows PowerShell 5.1 misreads BOM-less UTF-8.

param([switch]$Minimal)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Refresh-Path {
    # winget installs update the registry PATH, not this session's PATH.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Install-WithWinget($id, $label) {
    if (-not (Test-Command "winget")) {
        throw "winget not found. Install $label manually (or update 'App Installer' from the Microsoft Store), then re-run."
    }
    Write-Host "[..] installing $label"
    winget install --id $id -e --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

function Ensure-Tool($command, $wingetId, $label) {
    if (Test-Command $command) {
        Write-Host "[ok] $label"
        return
    }
    Install-WithWinget $wingetId $label
    if (-not (Test-Command $command)) {
        throw "$label installed but '$command' is not on PATH yet. Open a NEW PowerShell window and re-run this script."
    }
}

function Test-Python($exe, $extraArgs) {
    # 'python' can be a Microsoft Store stub that exists but fails: check it really runs.
    try {
        $version = & $exe @extraArgs --version 2>&1
        return (($LASTEXITCODE -eq 0) -and ("$version" -match "Python 3\.(9|1\d)"))
    } catch {
        return $false
    }
}

function Find-Python {
    if (Test-Python "py" @("-3")) { return @{ Exe = "py"; Args = @("-3") } }
    if (Test-Python "python" @()) { return @{ Exe = "python"; Args = @() } }
    return $null
}

function Invoke-Native {
    # Runs a program and says how it went: @{ Code = its exit code; Output = what it printed }. A program that fails must not end
    # this script by accident (Windows PowerShell turns a program's error output into a script error), and the exit code is the
    # only honest answer to "did it work": without it a failed install used to be reported as "[ok]".
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $exe = $args[0]
        $rest = @($args | Select-Object -Skip 1)
        $lines = & $exe @rest 2>&1 | ForEach-Object { "$_" }
        return @{ Code = $LASTEXITCODE; Output = ($lines -join "`n") }
    } finally {
        $ErrorActionPreference = $saved
    }
}

function Write-Utf8NoBom($path, $text) {
    # Claude Code's JSON parser dislikes a BOM; Set-Content -Encoding UTF8 adds one on PS 5.1.
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host "== 1/5 Base tools =="
if (-not $Minimal) {
    Ensure-Tool "git" "Git.Git" "Git"
    Ensure-Tool "node" "OpenJS.NodeJS.LTS" "Node.js LTS"
}
$python = Find-Python
if (-not $python) {
    if (-not (Test-Command "winget")) {
        throw "Python 3.9 or newer was not found, and winget is not available to install it. Install Python from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then double-click Start.bat again."
    }
    Install-WithWinget "Python.Python.3.12" "Python 3.12"
    $python = Find-Python
}
if (-not $python) { throw "Python 3.9+ still not found. Open a NEW PowerShell window and re-run." }
Write-Host "[ok] Python"

Write-Host "== 2/5 Claude Code =="
if ($Minimal) {
    Write-Host "[skip] not needed to apply to jobs"
} elseif (Test-Command "claude") {
    Write-Host "[ok] Claude Code"
} else {
    npm install -g "@anthropic-ai/claude-code"
    Refresh-Path
    if (-not (Test-Command "claude")) {
        Write-Host "[!!] 'claude' not on PATH yet; open a NEW PowerShell window after this script finishes."
    }
}

Write-Host "== 3/5 Project environment =="
$venvPython = ".\.venv\Scripts\python.exe"
$pipNetwork = @("--retries", "2", "--timeout", "20")
if (-not (Test-Path $venvPython)) {
    $venvArgs = @($python.Args) + @("-m", "venv", ".venv")
    $made = Invoke-Native $python.Exe @venvArgs
    if (($made.Code -ne 0) -or (-not (Test-Path $venvPython))) {
        Write-Host $made.Output
        throw "Could not create this program's private Python environment (.venv). The lines above say why."
    }
}
$upgradeArgs = @("-m", "pip", "install", "--quiet") + $pipNetwork + @("--upgrade", "pip")
[void](Invoke-Native $venvPython @upgradeArgs)   # best effort: being offline is fine here
$installArgs = @("-m", "pip", "install", "--quiet") + $pipNetwork + @("-e", ".")
Write-Host "Installing. This takes a minute or two the first time..."
$install = Invoke-Native $venvPython @installArgs
if ($install.Code -eq 0) {
    Write-Host "[ok] jobapply installed in .venv"
} elseif ((Invoke-Native $venvPython "-m" "jobapply" "--version").Code -eq 0) {
    Write-Host "[ok] already installed (could not reach the download site to look for updates, which is fine)"
} elseif ($install.Output -match "NameResolutionError|Failed to resolve|getaddrinfo|Max retries|timed out|ProxyError|SSLError|CERTIFICATE_VERIFY_FAILED|Connection") {
    Write-Host ""
    Write-Host "This PC cannot reach pypi.org, where this program's parts are downloaded."
    Write-Host "- No internet? Connect, then double-click Start.bat again."
    Write-Host "- On a work or school network that blocks it? Ask IT for the ""PyPI mirror"" web address and paste it below."
    Write-Host ""
    $mirror = ("" + (Read-Host "Mirror address (or just press Enter to stop)")).Trim()
    if (-not $mirror) { throw "Stopped. Double-click Start.bat again when you have an internet connection or the address." }
    if ($mirror -notmatch "^https?://") { throw "That does not look like a web address (it should start with https://). Double-click Start.bat to try again." }
    [void](Invoke-Native $venvPython "-m" "pip" "config" "--site" "set" "global.index-url" $mirror)
    $install = Invoke-Native $venvPython @installArgs
    if ($install.Code -ne 0) {
        Write-Host $install.Output
        throw "Still could not install this program's parts. The lines above say what went wrong."
    }
    Write-Host "[ok] installed (the address is remembered for next time, inside this folder's private environment)"
} else {
    Write-Host $install.Output
    throw "Could not install this program's parts. The lines above say what went wrong."
}
New-Item -ItemType Directory -Force "data" | Out-Null

# The engine drives BrowserOS neo (preferred) or Chrome. Install BrowserOS neo yourself;
# Chrome is only a fallback.
$browser = & .\.venv\Scripts\python.exe -c "from jobapply.browser import find_browser; print(find_browser() or '')"
if ($browser) {
    Write-Host "[ok] automation browser: $browser"
} else {
    Write-Host "[!!] BrowserOS neo not found. Install it, then re-run this script or set JOBAPPLY_BROWSER_EXE,"
    Write-Host "     or later run: jobapply browser --exe ""<path to BrowserOS neo exe>"""
    $answer = Read-Host "Install Google Chrome as a fallback browser now? (y/n)"
    if ($answer -match "^[yY]") { Install-WithWinget "Google.Chrome" "Google Chrome" }
}

Write-Host "== 4/5 OpenRouter (free models) =="
$apiKey = ""
if (-not $Minimal) {
    Write-Host "Create a key at https://openrouter.ai/keys, and in Settings -> Privacy turn OFF training on your data."
    Write-Host "Pick free models at https://openrouter.ai/models (filter: Free + supports tools, context >= 64k)."
    $secureKey = Read-Host "OpenRouter API key (press Enter to skip / keep existing)" -AsSecureString
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey))
}
if ($apiKey) {
    $models = Read-Host "Free model ids, comma-separated, first = primary (e.g. vendor/model:free,vendor/other:free)"
    $primary = ($models -split ",")[0].Trim()
    if (-not $primary) { throw "A model id is required when you give a key." }

    $settingsPath = Join-Path $env:USERPROFILE ".claude\settings.json"
    New-Item -ItemType Directory -Force (Split-Path $settingsPath) | Out-Null
    if (Test-Path $settingsPath) {
        $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
    } else {
        $settings = [pscustomobject]@{}
    }
    if (-not $settings.PSObject.Properties["env"]) {
        $settings | Add-Member -NotePropertyName env -NotePropertyValue ([pscustomobject]@{})
    }
    $values = [ordered]@{
        "ANTHROPIC_BASE_URL"                       = "https://openrouter.ai/api"
        "ANTHROPIC_AUTH_TOKEN"                     = $apiKey
        "ANTHROPIC_API_KEY"                        = ""
        "ANTHROPIC_DEFAULT_SONNET_MODEL"           = $primary
        "ANTHROPIC_DEFAULT_OPUS_MODEL"             = $primary
        "ANTHROPIC_DEFAULT_HAIKU_MODEL"            = $primary
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" = "1"
    }
    foreach ($name in $values.Keys) {
        $settings.env | Add-Member -NotePropertyName $name -NotePropertyValue $values[$name] -Force
    }
    Write-Utf8NoBom $settingsPath ($settings | ConvertTo-Json -Depth 10)
    Write-Host "[ok] Claude Code now talks to OpenRouter ($primary). Key stored in $settingsPath"
} else {
    Write-Host "[skip] OpenRouter not configured (the engine itself works without an LLM)."
}

Write-Host "== 5/5 BrowserOS MCP (optional, only for repairing selectors with Claude) =="
$endpoint = ""
if (-not $Minimal) {
    $endpoint = Read-Host "BrowserOS MCP endpoint from its 'Manual Setup' page (press Enter to skip)"
}
if ($endpoint -and (Test-Command "claude")) {
    claude mcp add --scope user --transport http browseros-neo $endpoint
}

if ($Minimal) {
    Write-Host ""
    Write-Host "Installed. Opening the control panel..."
    return
}

Write-Host ""
Write-Host "== Health check =="
& .\.venv\Scripts\jobapply.exe doctor

Write-Host ""
Write-Host "Next (the only manual steps left):"
Write-Host "  1. .\.venv\Scripts\Activate.ps1          (if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned)"
Write-Host "  2. jobapply browser                      -> opens BrowserOS neo (dedicated profile); log in to each portal ONCE"
Write-Host "  3. jobapply init --resume ""C:\path\resume.pdf""   -> interview; then set real years per skill in data\profile.yaml"
Write-Host "  4. jobapply probe naukri                 -> calibrate the portal (fix selectors if it finds no jobs)"
Write-Host "  5. claude                                -> run it INSIDE this folder; then say: apply on Naukri.com, resume C:\path\resume.pdf"
