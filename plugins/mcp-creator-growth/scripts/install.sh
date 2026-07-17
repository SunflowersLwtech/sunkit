#!/bin/bash
# MCP Creator Growth - Unix Installation Script
# Usage: curl -fsSL https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/install.sh | bash
#
# Environment variables:
#   MCP_INSTALL_PATH - Custom installation path (default: ~/mcp-creator-growth)
#   MCP_USE_UV       - Force use uv (set to "1" to enable)
#   MCP_USE_CONDA    - Force use conda (set to "1" to enable)

set -e

INSTALL_PATH="${MCP_INSTALL_PATH:-$HOME/mcp-creator-growth}"
PYTHON_VERSION_REQUIRED="3.11"
ENV_MANAGER=""
SCRIPT_PATH=""

echo "================================================"
echo "  MCP Creator Growth - Installation Script"
echo "================================================"
echo ""

# ============================================================================
# CHECK FOR EXISTING INSTALLATION
# ============================================================================

find_existing_installation() {
    local candidates=()

    # Check default installation path
    if [[ -f "$INSTALL_PATH/.env_manager" ]]; then
        candidates+=("$INSTALL_PATH")
    fi

    # Check pip installation
    if command -v pip &> /dev/null || command -v pip3 &> /dev/null; then
        local pip_cmd="pip"
        command -v pip3 &> /dev/null && pip_cmd="pip3"

        local pip_output=$($pip_cmd show mcp-creator-growth 2>/dev/null || true)
        if [[ -n "$pip_output" ]]; then
            local editable_location=$(echo "$pip_output" | grep "Editable project location:" | cut -d: -f2- | xargs)
            if [[ -n "$editable_location" && -d "$editable_location" ]]; then
                candidates+=("$editable_location")
            fi
        fi
    fi

    # Check common alternative locations
    local alt_paths=(
        "$HOME/Documents/mcp-creator-growth"
        "/opt/mcp-creator-growth"
    )

    for path in "${alt_paths[@]}"; do
        if [[ -f "$path/.env_manager" ]]; then
            candidates+=("$path")
        fi
    done

    # Remove duplicates
    local unique_candidates=($(printf "%s\n" "${candidates[@]}" | sort -u))

    echo "${unique_candidates[@]}"
}

echo "Checking for existing installation..."

existing_installations=($(find_existing_installation))

if [[ ${#existing_installations[@]} -gt 0 ]]; then
    echo ""
    echo "Existing installation detected!"
    echo ""

    for installation in "${existing_installations[@]}"; do
        echo "  Found: $installation"
        if [[ -f "$installation/src/mcp_creator_growth/__init__.py" ]]; then
            version=$(grep -oP '__version__\s*=\s*"\K[^"]+' "$installation/src/mcp_creator_growth/__init__.py" 2>/dev/null || echo "unknown")
            echo "  Version: $version"
        fi
    done

    echo ""
    echo "Running update instead of fresh installation..."
    echo ""

    # Download and execute update script
    if curl -fsSL https://raw.githubusercontent.com/SunflowersLwtech/mcp_creator_growth/main/scripts/update.sh | bash; then
        exit 0
    else
        echo "Failed to download update script. Trying local update..."
        local_update_script="${existing_installations[0]}/scripts/update.sh"
        if [[ -f "$local_update_script" ]]; then
            bash "$local_update_script"
            exit 0
        else
            echo "Warning: Could not run update script. Continuing with installation..."
        fi
    fi
fi

echo "No existing installation found. Proceeding with fresh installation..."
echo ""

# Function to check Python version
check_python_version() {
    local python_cmd="$1"
    local version=$($python_cmd --version 2>&1 | sed -n 's/Python \([0-9]*\.[0-9]*\).*/\1/p')
    local major=$(echo $version | cut -d. -f1)
    local minor=$(echo $version | cut -d. -f2)

    if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
        echo "$version"
        return 0
    fi
    return 1
}

# Function to install uv if not present
install_uv() {
    echo "  Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
}

# Step 1: Detect or install environment manager
echo "[1/4] Setting up Python environment..."

# Check user preference
if [ "$MCP_USE_UV" = "1" ]; then
    ENV_MANAGER="uv"
    if ! command -v uv &> /dev/null; then
        install_uv
    fi
elif [ "$MCP_USE_CONDA" = "1" ]; then
    ENV_MANAGER="conda"
    if ! command -v conda &> /dev/null; then
        echo "Error: MCP_USE_CONDA=1 but conda is not installed."
        echo "Please install Miniconda: https://docs.conda.io/en/latest/miniconda.html"
        exit 1
    fi
else
    # Auto-detect: prefer uv > conda > system python
    if command -v uv &> /dev/null; then
        ENV_MANAGER="uv"
        echo "  Detected: uv"
    elif command -v conda &> /dev/null; then
        ENV_MANAGER="conda"
        echo "  Detected: conda"
    elif command -v python3 &> /dev/null; then
        if version=$(check_python_version python3); then
            ENV_MANAGER="venv"
            echo "  Detected: Python $version (using venv)"
        else
            # System Python is too old, try to install uv
            echo "  System Python is too old. Installing uv..."
            install_uv
            ENV_MANAGER="uv"
        fi
    else
        # No Python found, install uv
        echo "  No Python found. Installing uv..."
        install_uv
        ENV_MANAGER="uv"
    fi
fi

echo "  Using: $ENV_MANAGER"

# Step 2: Clone or update repository
echo ""
echo "[2/4] Setting up repository..."
if [ -d "$INSTALL_PATH" ]; then
    echo "  Directory exists. Updating..."
    cd "$INSTALL_PATH"
    git pull origin main 2>/dev/null || true
else
    echo "  Cloning repository..."
    git clone https://github.com/SunflowersLwtech/mcp_creator_growth.git "$INSTALL_PATH"
    cd "$INSTALL_PATH"
fi

# Ensure scripts are executable
chmod +x "$INSTALL_PATH/scripts/"*.sh 2>/dev/null || true

# Step 3: Create virtual environment
echo ""
echo "[3/4] Creating virtual environment..."

case "$ENV_MANAGER" in
    "uv")
        if [ ! -d "mcp-creator-growth" ]; then
            uv venv --python $PYTHON_VERSION_REQUIRED mcp-creator-growth
            echo "  Virtual environment created with Python $PYTHON_VERSION_REQUIRED"
        else
            echo "  Virtual environment already exists."
        fi
        SCRIPT_PATH="$INSTALL_PATH/mcp-creator-growth/bin/mcp-creator-growth"
        ;;
    "conda")
        if ! conda env list | grep -q "mcp-creator-growth"; then
            conda create -n mcp-creator-growth python=$PYTHON_VERSION_REQUIRED -y
            echo "  Conda environment created."
        else
            echo "  Conda environment already exists."
        fi
        # Get conda env path
        CONDA_ENV_PATH=$(conda env list | grep "mcp-creator-growth" | awk '{print $NF}')
        SCRIPT_PATH="$CONDA_ENV_PATH/bin/mcp-creator-growth"
        ;;
    "venv")
        if [ ! -d "mcp-creator-growth" ]; then
            python3 -m venv mcp-creator-growth
            echo "  Virtual environment created."
        else
            echo "  Virtual environment already exists."
        fi
        SCRIPT_PATH="$INSTALL_PATH/mcp-creator-growth/bin/mcp-creator-growth"
        ;;
esac

# Step 4: Install dependencies
echo ""
echo "[4/4] Installing dependencies..."

case "$ENV_MANAGER" in
    "uv")
        uv pip install -e '.[dev]' --quiet
        ;;
    "conda")
        eval "$(conda shell.bash hook)"
        conda activate mcp-creator-growth
        pip install -e '.[dev]' --quiet
        conda deactivate
        ;;
    "venv")
        ./mcp-creator-growth/bin/pip install -e '.[dev]' --quiet
        ;;
esac

echo "  Dependencies installed."

# Save environment manager info for update script
echo "$ENV_MANAGER" > "$INSTALL_PATH/.env_manager"

echo ""
echo "================================================"
echo "  Installation Complete!"
echo "================================================"
echo ""
echo "Environment: $ENV_MANAGER"
echo "Command:     $SCRIPT_PATH"
echo ""
echo "================================================"
echo "  Configure Your IDE"
echo "================================================"
echo ""
echo "For Claude Code (one command):"
echo "  claude mcp add mcp-creator-growth -- $SCRIPT_PATH"
echo ""
echo "For other IDEs (Cursor, Windsurf, etc.), add this to MCP config:"
echo "  {"
echo "    \"mcp-creator-growth\": {"
echo "      \"command\": \"$SCRIPT_PATH\""
echo "    }"
echo "  }"
echo ""
echo "To update later, run:"
echo "  $INSTALL_PATH/scripts/update.sh"
echo ""
