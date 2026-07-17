# Quick Detection Test
Write-Host "Testing Installation Detection Logic" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Test 1: Check marker file
Write-Host "[Test 1] Checking for .env_manager file..." -ForegroundColor Yellow
if (Test-Path ".env_manager") {
    $envManager = Get-Content ".env_manager"
    Write-Host "  ✅ Found: .env_manager" -ForegroundColor Green
    Write-Host "  Environment: $envManager" -ForegroundColor Gray
} else {
    Write-Host "  ❌ Not found: .env_manager" -ForegroundColor Red
}

Write-Host ""

# Test 2: Check pip installation
Write-Host "[Test 2] Checking pip installation..." -ForegroundColor Yellow
try {
    $pipShow = pip show mcp-creator-growth 2>$null
    if ($pipShow) {
        $version = ($pipShow | Select-String "^Version:").ToString().Split()[1]
        $location = $pipShow | Select-String "Editable project location:"

        Write-Host "  ✅ Package installed" -ForegroundColor Green
        Write-Host "  Version: $version" -ForegroundColor Gray

        if ($location) {
            $pipPath = ($location -split ":", 2)[1].Trim()
            Write-Host "  Location: $pipPath" -ForegroundColor Gray
        }
    } else {
        Write-Host "  ❌ Package not found" -ForegroundColor Red
    }
} catch {
    Write-Host "  ❌ pip command failed" -ForegroundColor Red
}

Write-Host ""

# Test 3: Check code version
Write-Host "[Test 3] Checking code version..." -ForegroundColor Yellow
if (Test-Path "src\mcp_creator_growth\__init__.py") {
    $content = Get-Content "src\mcp_creator_growth\__init__.py" -Raw
    if ($content -match '__version__\s*=\s*"([^"]+)"') {
        $codeVersion = $Matches[1]
        Write-Host "  ✅ Code version: $codeVersion" -ForegroundColor Green
    } else {
        Write-Host "  ❌ Version not found in code" -ForegroundColor Red
    }
} else {
    Write-Host "  ❌ Source file not found" -ForegroundColor Red
}

Write-Host ""

# Test 4: Version sync check
Write-Host "[Test 4] Version synchronization check..." -ForegroundColor Yellow
if ($version -and $codeVersion) {
    if ($version -eq $codeVersion) {
        Write-Host "  ✅ Versions match: $version" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Version mismatch!" -ForegroundColor Yellow
        Write-Host "     Code:      $codeVersion" -ForegroundColor Gray
        Write-Host "     Installed: $version" -ForegroundColor Gray
        Write-Host "     Action:    Need to reinstall" -ForegroundColor Cyan
    }
}

Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Detection test complete" -ForegroundColor Cyan
