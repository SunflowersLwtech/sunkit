# Contributing to MCP Creator Growth

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Code Style](#code-style)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Project Structure](#project-structure)

---

## Code of Conduct

Please be respectful and constructive in all interactions. We welcome contributors of all experience levels.

---

## Getting Started

1. **Fork the repository** on GitHub

2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/mcp_creator_growth.git
   cd mcp_creator_growth
   ```

3. **Add upstream remote**:
   ```bash
   git remote add upstream https://github.com/SunflowersLwtech/mcp_creator_growth.git
   ```

---

## Development Setup

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Git | Latest |
| uv (recommended) | Latest |

### Setup Options

<details>
<summary><b>Option 1: Using uv (Recommended)</b></summary>

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment
uv venv --python 3.11 mcp-creator-growth

# Activate environment
source mcp-creator-growth/bin/activate          # macOS/Linux
# mcp-creator-growth\Scripts\activate           # Windows

# Install with dev dependencies
uv pip install -e '.[dev]'
```

</details>

<details>
<summary><b>Option 2: Using standard venv</b></summary>

```bash
# Create virtual environment
python -m venv mcp-creator-growth

# Activate environment
source mcp-creator-growth/bin/activate           # macOS/Linux
# mcp-creator-growth\Scripts\activate            # Windows

# Install with dev dependencies
pip install -e '.[dev]'
```

</details>

### Configure for Local Testing

After setup, configure Claude Code to use your local development version:

**Using CLI (recommended):**
```bash
# Add your local development server
claude mcp add --scope local mcp-creator-growth-dev -- $(pwd)/mcp-creator-growth/bin/mcp-creator-growth

# Or with debug logging enabled
claude mcp add --scope local mcp-creator-growth-dev \
  --env MCP_DEBUG=true \
  -- $(pwd)/mcp-creator-growth/bin/mcp-creator-growth
```

**Using JSON configuration** (`~/.claude.json`):
```json
{
  "mcpServers": {
    "mcp-creator-growth-dev": {
      "command": "/absolute/path/to/project/mcp-creator-growth/bin/mcp-creator-growth",
      "args": [],
      "env": {
        "MCP_DEBUG": "true"
      }
    }
  }
}
```

### Verify Installation

```bash
# Check the server starts correctly
python -c "import mcp_creator_growth; print(f'Version: {mcp_creator_growth.__version__}')"

# Run linting
ruff check src/

# In Claude Code, verify with
/mcp
```

---

## Making Changes

### Branch Naming Convention

| Prefix | Use Case |
|--------|----------|
| `feature/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation updates |
| `refactor/` | Code refactoring |
| `test/` | Test additions/changes |

### Development Workflow

1. **Create a branch**:
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes** and commit:
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```

3. **Keep your branch updated**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

### Commit Message Format

We follow [Conventional Commits](https://www.conventionalcommits.org/):

| Type | Description |
|------|-------------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation changes |
| `refactor:` | Code refactoring |
| `test:` | Test additions/changes |
| `chore:` | Build/tooling changes |

**Examples:**
```
feat: add timeout parameter to learning_session
fix: resolve WebSocket connection leak
docs: update README with new configuration options
refactor: simplify debug_search query logic
```

---

## Testing

### Running Tests

```bash
# Run all tests
pytest -v

# Run with verbose output
pytest -v --tb=short

# Run specific test file
pytest tests/test_server.py -v

# Run with coverage report
pytest --cov=src/mcp_creator_growth --cov-report=html
```

### Writing Tests

Tests should be placed in the `tests/` directory (create if needed):

```python
import pytest
from mcp_creator_growth.server import mcp

@pytest.mark.asyncio
async def test_learning_session_defaults():
    """Test learning_session with default parameters."""
    # Your test implementation
    pass

@pytest.mark.asyncio
async def test_debug_search_empty_results():
    """Test debug_search when no matches found."""
    # Your test implementation
    pass
```

### Test Guidelines

- Name test files `test_*.py`
- Name test functions `test_*`
- Use `pytest.mark.asyncio` for async tests
- Use fixtures for common setup
- Write descriptive docstrings

---

## Code Style

### Python Style Guidelines

| Rule | Description |
|------|-------------|
| Line length | Max 120 characters (configured in pyproject.toml) |
| Type hints | Required for function parameters and returns |
| Docstrings | Required for public functions |
| Formatting | Follow PEP 8 |

### Example Code Style

```python
from typing import Any

async def process_quiz_result(
    session_id: str,
    answers: list[str],
    score: int
) -> dict[str, Any]:
    """Process quiz results and update session.

    Args:
        session_id: Unique session identifier
        answers: List of user answers
        score: Quiz score (0-100)

    Returns:
        dict with status and updated session data
    """
    # Implementation
    pass
```

### Linting and Formatting

```bash
# Check for issues
ruff check src/

# Auto-fix issues
ruff check src/ --fix

# Check specific file
ruff check src/mcp_creator_growth/server.py
```

### Pre-commit Check

Before committing, ensure:
```bash
# Lint passes
ruff check src/

# Tests pass (if available)
pytest -v

# Import works
python -c "import mcp_creator_growth"
```

---

## Submitting a Pull Request

### Before Submitting

- [ ] Code follows style guidelines (`ruff check src/` passes)
- [ ] Tests pass (if applicable)
- [ ] Documentation updated if needed
- [ ] Commit messages follow convention

### PR Process

1. **Push your branch**:
   ```bash
   git push origin feature/my-feature
   ```

2. **Create Pull Request** on GitHub

3. **Fill out the PR template**:
   - Summary of changes
   - Related issue (if any)
   - Type of change
   - Testing performed

4. **Wait for CI** - automated checks will run:
   - Build verification (Python 3.11, 3.12 on Ubuntu/Windows/macOS)
   - Lint check (ruff)

5. **Address review feedback** - make requested changes and push updates

---

## Project Structure

```
mcp_creator_growth/
├── src/mcp_creator_growth/     # Main source code
│   ├── __init__.py             # Package init with version
│   ├── __main__.py             # Entry point
│   ├── server.py               # MCP server and tool definitions
│   ├── config.py               # Configuration management
│   ├── debug.py                # Debug logging utilities
│   ├── storage/                # Data persistence layer
│   │   ├── debug_index.py      # Debug experience storage
│   │   ├── retrieval.py        # RAG retrieval logic
│   │   ├── terms_index.py      # Programming terms storage
│   │   ├── path_resolver.py    # Storage path resolution
│   │   ├── session_storage.py  # Learning session storage
│   │   └── ...
│   ├── web/                    # Web UI components
│   │   ├── main.py             # FastAPI app and WebSocket
│   │   ├── models/             # Data models
│   │   ├── routes/             # HTTP routes
│   │   └── websocket/          # WebSocket handlers
│   └── utils/                  # Utility functions
├── scripts/                    # Installation scripts
│   ├── install.sh              # Unix installer
│   ├── install.ps1             # Windows installer
│   ├── update.sh               # Unix updater
│   └── update.ps1              # Windows updater
├── assets/                     # Images and static assets
├── .github/                    # GitHub configuration
│   ├── workflows/ci.yml        # CI pipeline
│   ├── ISSUE_TEMPLATE/         # Issue templates
│   └── pull_request_template.md
├── pyproject.toml              # Project configuration
├── README.md                   # English documentation
├── README_zh-CN.md             # Simplified Chinese docs
├── README_zh-TW.md             # Traditional Chinese docs
└── CONTRIBUTING.md             # This file
```

### Key Files

| File | Purpose |
|------|---------|
| `server.py` | MCP tool definitions (`learning_session`, `debug_search`, `debug_record`, `term_get`, `get_system_info`) |
| `web/main.py` | FastAPI WebUI server with WebSocket support |
| `storage/debug_index.py` | Debug experience indexing and storage |
| `storage/retrieval.py` | RAG-based search for debug experiences |
| `storage/terms_index.py` | Programming terminology database |
| `config.py` | TOML configuration handling |

### Data Storage

All user data is stored locally in `.mcp-sidecar/`:
```
.mcp-sidecar/
├── debug/              # Debug experiences (JSON)
├── learning/           # Learning session history
├── terms/              # Shown terms tracking
└── config.toml         # User configuration
```

---

## Questions?

- **Issues**: Open an [Issue](https://github.com/SunflowersLwtech/mcp_creator_growth/issues)
- **Discussions**: Check existing issues before creating new ones
- **Context**: Provide as much detail as possible

Thank you for contributing!
