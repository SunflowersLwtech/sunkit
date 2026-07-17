#!/usr/bin/env bash
# MCP Creator Growth - Linux/macOS Update Script
#
# Usage (Remote - Recommended):
#   curl -fsSL https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/update.sh | bash
#
# Usage (Local):
#   ./scripts/update.sh
#   ./scripts/update.sh --path /custom/path
#
# Options:
#   --path PATH  - Specify installation path manually
#   --force      - Force update even if file is locked

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

# Parse arguments
INSTALL_PATH=""
FORCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --path)
            INSTALL_PATH="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  MCP Creator Growth - Update Script${NC}"
echo -e "${CYAN}================================================${NC}"
echo ""

# ============================================================================
# INSTALLATION DETECTION SYSTEM
# ============================================================================

find_installation_path() {
    echo -e "${YELLOW}[1/5] Detecting installation location...${NC}"

    local candidates=()
    local candidate_sources=()
    local candidate_priorities=()

    # Method 1: Check if running from local scripts directory
    if [[ -n "${BASH_SOURCE[0]}" && -f "$(dirname "${BASH_SOURCE[0]}")/../pyproject.toml" ]]; then
        local local_path="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
        candidates+=("$local_path")
        candidate_sources+=("Script Location")
        candidate_priorities+=(1)
        echo -e "${GRAY}  Found: $local_path (script location)${NC}"
    fi

    # Method 2: Scan for .env_manager marker file
    local search_paths=(
        "$HOME/mcp-creator-growth"
        "$HOME/Documents/mcp-creator-growth"
        "$HOME/Desktop/mcp-creator-growth"
        "$HOME/projects/mcp-creator-growth"
        "/opt/mcp-creator-growth"
        "/mnt/c/Users/${USER}/mcp-creator-growth"
        "/mnt/c/Users/${USER}/Documents/mcp-creator-growth"
        "/mnt/c/projects/mcp-creator-growth"
        "/mnt/d/projects/mcp-creator-growth"
        "/mnt/e/projects/mcp-creator-growth"
    )

    for path in "${search_paths[@]}"; do
        if [[ -f "$path/.env_manager" ]]; then
            # Check if already added
            local already_added=false
            for existing in "${candidates[@]}"; do
                if [[ "$existing" == "$path" ]]; then
                    already_added=true
                    break
                fi
            done
            if [[ "$already_added" == false ]]; then
                candidates+=("$path")
                candidate_sources+=(".env_manager")
                candidate_priorities+=(2)
                echo -e "${GRAY}  Found: $path (marker file)${NC}"
            fi
        fi
    done

    # Method 3: Check pip installed package location
    if command -v pip &> /dev/null; then
        local pip_output=$(pip show mcp-creator-growth 2>/dev/null || true)
        if [[ -n "$pip_output" ]]; then
            local editable_location=$(echo "$pip_output" | grep "Editable project location:" | cut -d: -f2- | xargs)
            if [[ -n "$editable_location" && -d "$editable_location" ]]; then
                # Check if already added
                local already_added=false
                for existing in "${candidates[@]}"; do
                    if [[ "$existing" == "$editable_location" ]]; then
                        already_added=true
                        break
                    fi
                done
                if [[ "$already_added" == false ]]; then
                    candidates+=("$editable_location")
                    candidate_sources+=("pip (editable)")
                    candidate_priorities+=(3)
                    echo -e "${GRAY}  Found: $editable_location (pip editable)${NC}"
                fi
            fi
        fi
    fi

    # Sort by priority and remove any remaining duplicates
    local unique_candidates=()
    local unique_sources=()
    local seen_paths=()

    # Create sorted index array
    local sorted_indices=($(
        for i in "${!candidates[@]}"; do
            echo "$i ${candidate_priorities[$i]}"
        done | sort -k2 -n | cut -d' ' -f1
    ))

    for i in "${sorted_indices[@]}"; do
        local candidate="${candidates[$i]}"
        local already_seen=false
        for seen in "${seen_paths[@]}"; do
            if [[ "$candidate" == "$seen" ]]; then
                already_seen=true
                break
            fi
        done
        if [[ "$already_seen" == false ]]; then
            unique_candidates+=("$candidate")
            unique_sources+=("${candidate_sources[$i]}")
            seen_paths+=("$candidate")
            if [[ ${#unique_candidates[@]} -ge 5 ]]; then
                break
            fi
        fi
    done

    if [[ ${#unique_candidates[@]} -eq 0 ]]; then
        echo ""
        echo -e "${RED}Error: No installation found!${NC}"
        echo ""
        echo -e "${YELLOW}Please install first:${NC}"
        echo -e "${NC}  curl -fsSL https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/install.sh | bash${NC}"
        echo ""
        exit 1
    fi

    if [[ ${#unique_candidates[@]} -eq 1 ]]; then
        INSTALL_PATH="${unique_candidates[0]}"
        echo -e "${GREEN}  Selected: $INSTALL_PATH${NC}"
        echo ""
        return 0
    fi

    # Multiple installations found
    echo ""
    echo -e "${YELLOW}Multiple installations detected:${NC}"
    echo ""

    for i in "${!unique_candidates[@]}"; do
        local idx=$((i + 1))
        echo -e "${NC}  [$idx] ${unique_candidates[$i]}${NC}"
        echo -e "${GRAY}      Source: ${unique_sources[$i]}${NC}"

        # Get version if possible
        local version_file="${unique_candidates[$i]}/src/mcp_creator_growth/__init__.py"
        if [[ -f "$version_file" ]]; then
            local version=$(grep -oP '__version__\s*=\s*"\K[^"]+' "$version_file" 2>/dev/null || echo "unknown")
            echo -e "${GRAY}      Version: $version${NC}"
        fi
        echo ""
    done

    # Auto-select the first one (highest priority)
    INSTALL_PATH="${unique_candidates[0]}"
    echo -e "${CYAN}Auto-selecting [1] (highest priority)${NC}"
    echo -e "${GRAY}To update a different installation, run:${NC}"
    echo -e "${GRAY}  ./scripts/update.sh --path \"<path>\"${NC}"
    echo ""
}

# Detect installation path
if [[ -z "$INSTALL_PATH" ]]; then
    find_installation_path
else
    echo -e "${YELLOW}[1/5] Using specified path...${NC}"
    echo -e "${GRAY}  Path: $INSTALL_PATH${NC}"
    echo ""
    if [[ ! -d "$INSTALL_PATH" ]]; then
        echo -e "${RED}Error: Specified path does not exist!${NC}"
        exit 1
    fi
fi

cd "$INSTALL_PATH"

# ============================================================================
# ENVIRONMENT DETECTION
# ============================================================================

echo -e "${YELLOW}[2/5] Detecting environment...${NC}"

# Read environment manager from saved file
if [[ -f ".env_manager" ]]; then
    ENV_MANAGER=$(cat ".env_manager" | tr -d '[:space:]')
    echo -e "${GREEN}  Environment: $ENV_MANAGER${NC}"
else
    # Fallback: detect from existing environment
    # Check new naming convention first
    if [[ -d "mcp-creator-growth" ]]; then
        # Could be uv or venv, check pyvenv.cfg
        if [[ -f "mcp-creator-growth/pyvenv.cfg" ]]; then
            if grep -q "uv" "mcp-creator-growth/pyvenv.cfg" 2>/dev/null; then
                ENV_MANAGER="uv"
            else
                ENV_MANAGER="venv"
            fi
        else
            ENV_MANAGER="venv"  # Default assumption
        fi
    elif conda env list 2>/dev/null | grep -q "mcp-creator-growth"; then
        ENV_MANAGER="conda"
    elif [[ -d ".venv" ]]; then
        # Legacy uv installation
        ENV_MANAGER="uv"
        echo -e "${YELLOW}  Detected legacy .venv directory${NC}"
    elif [[ -d "venv" ]]; then
        # Legacy venv installation
        ENV_MANAGER="venv"
        echo -e "${YELLOW}  Detected legacy venv directory${NC}"
    else
        echo -e "${RED}  Error: Cannot detect environment manager.${NC}"
        echo -e "${YELLOW}  Please run install script again:${NC}"
        echo -e "${NC}    curl -fsSL https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/install.sh | bash${NC}"
        exit 1
    fi
    echo -e "${GREEN}  Environment: $ENV_MANAGER (detected)${NC}"
fi

# Get current version
CURRENT_VERSION="unknown"
if [[ -f "src/mcp_creator_growth/__init__.py" ]]; then
    CURRENT_VERSION=$(grep -oP '__version__\s*=\s*"\K[^"]+' "src/mcp_creator_growth/__init__.py" 2>/dev/null || echo "unknown")
fi

echo -e "${GRAY}  Current version: $CURRENT_VERSION${NC}"
echo ""

# ============================================================================
# UPDATE REPOSITORY
# ============================================================================

echo -e "${YELLOW}[3/5] Pulling latest changes...${NC}"

git fetch origin main 2>&1 > /dev/null || true
LOCAL_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE_COMMIT=$(git rev-parse origin/main 2>/dev/null || echo "")

if [[ "$LOCAL_COMMIT" == "$REMOTE_COMMIT" && -n "$LOCAL_COMMIT" ]]; then
    echo -e "${GREEN}  Already up to date!${NC}"
    echo -e "${GRAY}  Version: $CURRENT_VERSION${NC}"
    exit 0
fi

# Pull changes with proper error handling
if git pull origin main 2>&1 | grep -q "Already up to date"; then
    echo -e "${GREEN}  Already up to date!${NC}"
elif git pull origin main &> /dev/null; then
    echo -e "${GREEN}  Changes pulled successfully.${NC}"
else
    # Try reset as fallback
    echo -e "${YELLOW}  Using git reset to sync with remote...${NC}"
    if git reset --hard origin/main &> /dev/null; then
        echo -e "${GREEN}  Repository updated.${NC}"
    else
        echo -e "${YELLOW}  Warning: Git sync had issues, but continuing...${NC}"
    fi
fi

echo ""

# ============================================================================
# UPDATE DEPENDENCIES
# ============================================================================

echo -e "${YELLOW}[4/5] Updating dependencies...${NC}"

# Determine exe path based on environment
case $ENV_MANAGER in
    uv)
        # Check new location first, then legacy
        NEW_PATH="$INSTALL_PATH/mcp-creator-growth/bin/mcp-creator-growth"
        LEGACY_PATH="$INSTALL_PATH/.venv/bin/mcp-creator-growth"
        if [[ -f "$NEW_PATH" ]]; then
            EXE_PATH="$NEW_PATH"
        elif [[ -f "$LEGACY_PATH" ]]; then
            EXE_PATH="$LEGACY_PATH"
        else
            EXE_PATH="$NEW_PATH"  # Default for new installations
        fi
        ;;
    conda)
        CONDA_ENV_PATH=$(conda env list 2>/dev/null | grep "mcp-creator-growth" | awk '{print $NF}')
        if [[ -n "$CONDA_ENV_PATH" ]]; then
            EXE_PATH="$CONDA_ENV_PATH/bin/mcp-creator-growth"
        else
            EXE_PATH=""
        fi
        ;;
    venv)
        # Check new location first, then legacy
        NEW_PATH="$INSTALL_PATH/mcp-creator-growth/bin/mcp-creator-growth"
        LEGACY_PATH="$INSTALL_PATH/venv/bin/mcp-creator-growth"
        if [[ -f "$NEW_PATH" ]]; then
            EXE_PATH="$NEW_PATH"
        elif [[ -f "$LEGACY_PATH" ]]; then
            EXE_PATH="$LEGACY_PATH"
        else
            EXE_PATH="$NEW_PATH"  # Default for new installations
        fi
        ;;
esac

# Check if exe is locked
IS_LOCKED=false
if [[ -n "$EXE_PATH" && -f "$EXE_PATH" ]]; then
    if ! lsof "$EXE_PATH" &> /dev/null; then
        IS_LOCKED=false
    else
        IS_LOCKED=true
    fi
fi

if [[ "$IS_LOCKED" == true && "$FORCE" == false ]]; then
    echo ""
    echo -e "${YELLOW}  WARNING: MCP server is currently in use!${NC}"
    echo -e "${YELLOW}  An AI coding assistant or IDE is using this server.${NC}"
    echo ""
    echo -e "${CYAN}  To update successfully:${NC}"
    echo -e "${NC}    1. Close your AI coding assistant${NC}"
    echo -e "${GRAY}       (Claude Code, Cursor, Windsurf, etc.)${NC}"
    echo -e "${NC}    2. Run this command again:${NC}"
    echo -e "${GRAY}       curl -fsSL https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/update.sh | bash${NC}"
    echo ""
    echo -e "${GRAY}  Or use --force to skip dependency update:${NC}"
    echo -e "${GRAY}    curl -fsSL ... | bash -s -- --force${NC}"
    echo ""
    exit 1
fi

if [[ "$FORCE" == true && "$IS_LOCKED" == true ]]; then
    echo -e "${YELLOW}  Skipping dependency update (file locked)...${NC}"
else
    # Force reinstall to ensure version sync
    case $ENV_MANAGER in
        uv)
            # Check new location first, then legacy
            if [[ -f "mcp-creator-growth/bin/activate" ]]; then
                source mcp-creator-growth/bin/activate
            elif [[ -f ".venv/bin/activate" ]]; then
                source .venv/bin/activate
            fi

            if uv pip install -e '.[dev]' --reinstall --quiet; then
                echo -e "${GREEN}  Dependencies updated.${NC}"
            else
                echo -e "${YELLOW}  Warning: Dependency update encountered issues.${NC}"
            fi
            ;;
        conda)
            if conda activate mcp-creator-growth 2>/dev/null && pip install -e '.[dev]' --force-reinstall --no-deps --quiet && conda deactivate 2>/dev/null; then
                echo -e "${GREEN}  Dependencies updated.${NC}"
            else
                echo -e "${YELLOW}  Warning: Dependency update encountered issues.${NC}"
            fi
            ;;
        venv)
            # Check new location first, then legacy
            if [[ -f "mcp-creator-growth/bin/activate" ]]; then
                source mcp-creator-growth/bin/activate
            elif [[ -f "venv/bin/activate" ]]; then
                source venv/bin/activate
            fi

            if pip install -e '.[dev]' --force-reinstall --no-deps --quiet; then
                echo -e "${GREEN}  Dependencies updated.${NC}"
            else
                echo -e "${YELLOW}  Warning: Dependency update encountered issues.${NC}"
            fi
            ;;
    esac
fi

echo ""

# ============================================================================
# VERIFY VERSION
# ============================================================================

echo -e "${YELLOW}[5/5] Verifying installation...${NC}"

# Get new version
NEW_VERSION="unknown"
if [[ -f "src/mcp_creator_growth/__init__.py" ]]; then
    NEW_VERSION=$(grep -oP '__version__\s*=\s*"\K[^"]+' "src/mcp_creator_growth/__init__.py" 2>/dev/null || echo "unknown")
fi

# Verify installed version matches code version
INSTALLED_VERSION="unknown"
if command -v pip &> /dev/null; then
    INSTALLED_VERSION=$(pip show mcp-creator-growth 2>/dev/null | grep "^Version:" | cut -d: -f2 | xargs || echo "unknown")
fi

if [[ "$NEW_VERSION" != "unknown" ]]; then
    if [[ "$INSTALLED_VERSION" == "$NEW_VERSION" ]]; then
        echo -e "${GREEN}  Version: $NEW_VERSION${NC}"
        echo -e "${GREEN}  Status: Synchronized${NC}"
    else
        echo -e "${YELLOW}  Code version: $NEW_VERSION${NC}"
        echo -e "${YELLOW}  Installed version: $INSTALLED_VERSION${NC}"
        echo -e "${YELLOW}  Status: Version mismatch (restart IDE to update)${NC}"
    fi
else
    echo -e "${GREEN}  Updated: $CURRENT_VERSION -> $NEW_VERSION${NC}"
fi

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Update Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${CYAN}Please restart your AI coding assistant to apply changes.${NC}"
echo -e "${GRAY}(Claude Code, Cursor, Windsurf, VS Code, etc.)${NC}"
echo ""
