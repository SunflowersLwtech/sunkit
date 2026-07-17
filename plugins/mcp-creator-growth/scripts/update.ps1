# MCP Creator Growth - Windows Update Script
#
# Usage (Remote - Recommended):
#   irm https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/update.ps1 | iex
#
# Usage (Local):
#   .\scripts\update.ps1
#   .\scripts\update.ps1 -InstallPath "C:\custom\path"
#
# Parameters:
#   -InstallPath - Specify installation path manually
#   -Force       - Force update even if file is locked

param(
    [string]$InstallPath = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  MCP Creator Growth - Update Script" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# INSTALLATION DETECTION SYSTEM
# ============================================================================

function Find-InstallationPath {
    Write-Host "[1/5] Detecting installation location..." -ForegroundColor Yellow

    $candidates = @()

    # Method 1: Check if running from local scripts directory
    if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "..\pyproject.toml"))) {
        $localPath = Split-Path $PSScriptRoot -Parent
        $candidates += @{Path=$localPath; Source="Script Location"; Priority=1}
        Write-Host "  Found: $localPath (script location)" -ForegroundColor Gray
    }

    # Method 2: Scan for .env_manager marker file (written by install.ps1)
    # Check common locations without iterating all drives to avoid duplicates
    $searchPaths = @(
        (Join-Path $env:USERPROFILE "mcp-creator-growth"),
        (Join-Path $env:USERPROFILE "Documents\mcp-creator-growth"),
        (Join-Path $env:USERPROFILE "Desktop\mcp-creator-growth"),
        (Join-Path $env:USERPROFILE "Projects\mcp-creator-growth"),
        "C:\projects\mcp-creator-growth",
        "D:\projects\mcp-creator-growth",
        "E:\projects\mcp-creator-growth"
    )

    foreach ($path in $searchPaths) {
        if ((Test-Path $path) -and (Test-Path (Join-Path $path ".env_manager"))) {
            # Check if already in candidates by Path
            $alreadyAdded = $false
            foreach ($existing in $candidates) {
                if ($existing.Path -eq $path) {
                    $alreadyAdded = $true
                    break
                }
            }
            if (-not $alreadyAdded) {
                $candidates += @{Path=$path; Source=".env_manager"; Priority=2}
                Write-Host "  Found: $path (marker file)" -ForegroundColor Gray
            }
        }
    }

    # Method 3: Check pip installed package location
    try {
        $pipShow = pip show mcp-creator-growth 2>$null
        if ($pipShow) {
            $editableLocation = $pipShow | Select-String "Editable project location:"
            if ($editableLocation) {
                $pipPath = ($editableLocation -split ":", 2)[1].Trim()
                if (Test-Path $pipPath) {
                    # Check if already in candidates
                    $alreadyAdded = $false
                    foreach ($existing in $candidates) {
                        if ($existing.Path -eq $pipPath) {
                            $alreadyAdded = $true
                            break
                        }
                    }
                    if (-not $alreadyAdded) {
                        $candidates += @{Path=$pipPath; Source="pip (editable)"; Priority=3}
                        Write-Host "  Found: $pipPath (pip editable)" -ForegroundColor Gray
                    }
                }
            }
        }
    } catch {
        # Silently ignore pip errors
    }

    # Method 4: Search Windows Additional Working Directories (if multiple installations)
    $workingDirs = @(
        (Join-Path $env:USERPROFILE "mcp-creator-growth"),
        (Join-Path $env:USERPROFILE "Documents\mcp-creator-growth")
    )
    foreach ($dir in $workingDirs) {
        if ((Test-Path $dir) -and (Test-Path (Join-Path $dir "pyproject.toml"))) {
            # Check if already in candidates
            $exists = $candidates | Where-Object { $_.Path -eq $dir }
            if (-not $exists) {
                $candidates += @{Path=$dir; Source="Known Location"; Priority=4}
                Write-Host "  Found: $dir (known location)" -ForegroundColor Gray
            }
        }
    }

    # Remove duplicates and sort by priority (manual deduplication)
    $seenPaths = @{}
    $uniqueCandidates = @()
    foreach ($candidate in ($candidates | Sort-Object -Property Priority)) {
        if (-not $seenPaths.ContainsKey($candidate.Path)) {
            $seenPaths[$candidate.Path] = $true
            $uniqueCandidates += $candidate
            if ($uniqueCandidates.Count -ge 5) { break }
        }
    }

    if ($uniqueCandidates.Count -eq 0) {
        Write-Host ""
        Write-Host "Error: No installation found!" -ForegroundColor Red
        Write-Host ""
        Write-Host "Please install first:" -ForegroundColor Yellow
        Write-Host "  irm https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/install.ps1 | iex" -ForegroundColor White
        Write-Host ""
        exit 1
    }

    if ($uniqueCandidates.Count -eq 1) {
        $selected = $uniqueCandidates[0]
        Write-Host "  Selected: $($selected.Path)" -ForegroundColor Green
        Write-Host ""
        return $selected.Path
    }

    # Multiple installations found - ask user to choose
    Write-Host ""
    Write-Host "Multiple installations detected:" -ForegroundColor Yellow
    Write-Host ""

    for ($i = 0; $i -lt $uniqueCandidates.Count; $i++) {
        $candidate = $uniqueCandidates[$i]
        Write-Host "  [$($i+1)] $($candidate.Path)" -ForegroundColor White
        Write-Host "      Source: $($candidate.Source)" -ForegroundColor Gray

        # Get version if possible
        $versionFile = Join-Path $candidate.Path "src\mcp_creator_growth\__init__.py"
        if (Test-Path $versionFile) {
            $content = Get-Content $versionFile -Raw
            if ($content -match '__version__\s*=\s*"([^"]+)"') {
                Write-Host "      Version: $($Matches[1])" -ForegroundColor Gray
            }
        }
        Write-Host ""
    }

    # Auto-select the first one (highest priority)
    Write-Host "Auto-selecting [1] (highest priority)" -ForegroundColor Cyan
    Write-Host "To update a different installation, run:" -ForegroundColor Gray
    Write-Host "  .\scripts\update.ps1 -InstallPath `"<path>`"" -ForegroundColor Gray
    Write-Host ""

    return $uniqueCandidates[0].Path
}

# Detect installation path
if (-not $InstallPath) {
    $InstallPath = Find-InstallationPath
} else {
    Write-Host "[1/5] Using specified path..." -ForegroundColor Yellow
    Write-Host "  Path: $InstallPath" -ForegroundColor Gray
    Write-Host ""
    if (-not (Test-Path $InstallPath)) {
        Write-Host "Error: Specified path does not exist!" -ForegroundColor Red
        exit 1
    }
}

Push-Location $InstallPath

# ============================================================================
# ENVIRONMENT DETECTION
# ============================================================================

Write-Host "[2/5] Detecting environment..." -ForegroundColor Yellow

# Read environment manager from saved file
if (Test-Path ".env_manager") {
    $EnvManager = Get-Content ".env_manager" -Raw
    $EnvManager = $EnvManager.Trim()
    Write-Host "  Environment: $EnvManager" -ForegroundColor Green
} else {
    # Fallback: detect from existing environment
    # Check for new naming convention first
    if (Test-Path "mcp-creator-growth") {
        # Could be uv or venv, check for uv-specific files
        if (Test-Path "mcp-creator-growth\pyvenv.cfg") {
            $cfg = Get-Content "mcp-creator-growth\pyvenv.cfg" -Raw
            if ($cfg -match "uv") {
                $EnvManager = "uv"
            } else {
                $EnvManager = "venv"
            }
        } else {
            $EnvManager = "venv"  # Default assumption
        }
    } elseif ((conda env list 2>$null | Select-String "mcp-creator-growth")) {
        $EnvManager = "conda"
    } elseif (Test-Path ".venv") {
        # Legacy uv installation
        $EnvManager = "uv"
        Write-Host "  Detected legacy .venv directory" -ForegroundColor Yellow
    } elseif (Test-Path "venv") {
        # Legacy venv installation
        $EnvManager = "venv"
        Write-Host "  Detected legacy venv directory" -ForegroundColor Yellow
    } else {
        Write-Host "  Error: Cannot detect environment manager." -ForegroundColor Red
        Write-Host "  Please run install script again:" -ForegroundColor Yellow
        Write-Host "    irm https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/install.ps1 | iex" -ForegroundColor White
        Pop-Location
        exit 1
    }
    Write-Host "  Environment: $EnvManager (detected)" -ForegroundColor Green
}

# Get current version
$currentVersion = "unknown"
try {
    $initFile = Get-Content "src\mcp_creator_growth\__init__.py" -Raw
    if ($initFile -match '__version__\s*=\s*"([^"]+)"') {
        $currentVersion = $Matches[1]
    }
} catch {}

Write-Host "  Current version: $currentVersion" -ForegroundColor Gray
Write-Host ""

# ============================================================================
# UPDATE REPOSITORY
# ============================================================================

Write-Host "[3/5] Pulling latest changes..." -ForegroundColor Yellow

try {
    git fetch origin main 2>&1 | Out-Null
    $localCommit = git rev-parse HEAD
    $remoteCommit = git rev-parse origin/main

    if ($localCommit -eq $remoteCommit) {
        Write-Host "  Already up to date!" -ForegroundColor Green
        Write-Host "  Version: $currentVersion" -ForegroundColor Gray
        Pop-Location
        exit 0
    }

    # Pull changes with proper error handling
    $gitOutput = git pull origin main 2>&1
    if ($LASTEXITCODE -eq 0 -or $gitOutput -match "Already up to date") {
        Write-Host "  Changes pulled successfully." -ForegroundColor Green
    } else {
        # Try reset as fallback
        Write-Host "  Using git reset to sync with remote..." -ForegroundColor Yellow
        git reset --hard origin/main 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Repository updated." -ForegroundColor Green
        } else {
            Write-Host "  Warning: Git sync had issues, but continuing..." -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "  Warning: Git update encountered errors, continuing..." -ForegroundColor Yellow
}

Write-Host ""

# ============================================================================
# UPDATE DEPENDENCIES
# ============================================================================

Write-Host "[4/5] Updating dependencies..." -ForegroundColor Yellow

# Determine exe path based on environment
$ExePath = switch ($EnvManager) {
    "uv" {
        # Check new location first, then legacy
        $newPath = Join-Path $InstallPath "mcp-creator-growth\Scripts\mcp-creator-growth.exe"
        $legacyPath = Join-Path $InstallPath ".venv\Scripts\mcp-creator-growth.exe"
        if (Test-Path $newPath) { $newPath } elseif (Test-Path $legacyPath) { $legacyPath } else { $newPath }
    }
    "conda" {
        $condaInfo = conda env list 2>$null | Select-String "mcp-creator-growth"
        if ($condaInfo) {
            $CondaEnvPath = ($condaInfo -split '\s+')[-1]
            Join-Path $CondaEnvPath "Scripts\mcp-creator-growth.exe"
        } else { $null }
    }
    "venv" {
        # Check new location first, then legacy
        $newPath = Join-Path $InstallPath "mcp-creator-growth\Scripts\mcp-creator-growth.exe"
        $legacyPath = Join-Path $InstallPath "venv\Scripts\mcp-creator-growth.exe"
        if (Test-Path $newPath) { $newPath } elseif (Test-Path $legacyPath) { $legacyPath } else { $newPath }
    }
}

# Check if exe is locked
$isLocked = $false
if ($ExePath -and (Test-Path $ExePath)) {
    try {
        $file = [System.IO.File]::Open($ExePath, 'Open', 'Write')
        $file.Close()
    } catch {
        $isLocked = $true
    }
}

if ($isLocked -and -not $Force) {
    Write-Host ""
    Write-Host "  WARNING: MCP server is currently in use!" -ForegroundColor Yellow
    Write-Host "  An AI coding assistant or IDE is using this server." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  To update successfully:" -ForegroundColor Cyan
    Write-Host "    1. Close your AI coding assistant" -ForegroundColor White
    Write-Host "       (Claude Code, Cursor, Windsurf, etc.)" -ForegroundColor Gray
    Write-Host "    2. Run this command again:" -ForegroundColor White
    Write-Host "       irm https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/update.ps1 | iex" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Or use -Force to skip dependency update:" -ForegroundColor Gray
    Write-Host "    irm ... | iex -Force" -ForegroundColor Gray
    Write-Host ""
    Pop-Location
    exit 1
}

if ($Force -and $isLocked) {
    Write-Host "  Skipping dependency update (file locked)..." -ForegroundColor Yellow
} else {
    # Force reinstall to ensure version sync
    try {
        switch ($EnvManager) {
            "uv" {
                uv pip install -e ".[dev]" --reinstall --quiet
            }
            "conda" {
                $null = conda activate mcp-creator-growth 2>&1
                pip install -e ".[dev]" --force-reinstall --no-deps --quiet
                $null = conda deactivate 2>&1
            }
            "venv" {
                # Check new location first, then legacy
                $newPipPath = Join-Path $InstallPath "mcp-creator-growth\Scripts\pip.exe"
                $legacyPipPath = Join-Path $InstallPath "venv\Scripts\pip.exe"
                $pipPath = if (Test-Path $newPipPath) { $newPipPath } else { $legacyPipPath }
                & $pipPath install -e ".[dev]" --force-reinstall --no-deps --quiet
            }
        }
        Write-Host "  Dependencies updated." -ForegroundColor Green
    } catch {
        Write-Host "  Warning: Dependency update encountered issues." -ForegroundColor Yellow
        Write-Host "  Error: $_" -ForegroundColor Gray
    }
}

Write-Host ""

# ============================================================================
# VERIFY VERSION
# ============================================================================

Write-Host "[5/5] Verifying installation..." -ForegroundColor Yellow

# Get new version
$newVersion = "unknown"
try {
    $initFile = Get-Content "src\mcp_creator_growth\__init__.py" -Raw
    if ($initFile -match '__version__\s*=\s*"([^"]+)"') {
        $newVersion = $Matches[1]
    }
} catch {}

# Verify installed version matches code version
$installedVersion = "unknown"
try {
    $pipOutput = pip show mcp-creator-growth 2>$null
    if ($pipOutput) {
        $versionLine = $pipOutput | Select-String "^Version:"
        if ($versionLine) {
            $installedVersion = ($versionLine -split ":", 2)[1].Trim()
        }
    }
} catch {}

if ($newVersion -ne "unknown") {
    if ($installedVersion -eq $newVersion) {
        Write-Host "  Version: $newVersion" -ForegroundColor Green
        Write-Host "  Status: Synchronized" -ForegroundColor Green
    } else {
        Write-Host "  Code version: $newVersion" -ForegroundColor Yellow
        Write-Host "  Installed version: $installedVersion" -ForegroundColor Yellow
        Write-Host "  Status: Version mismatch (restart IDE to update)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  Updated: $currentVersion -> $newVersion" -ForegroundColor Green
}

Pop-Location

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  Update Complete!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Please restart your AI coding assistant to apply changes." -ForegroundColor Cyan
Write-Host "(Claude Code, Cursor, Windsurf, VS Code, etc.)" -ForegroundColor Gray
Write-Host ""
