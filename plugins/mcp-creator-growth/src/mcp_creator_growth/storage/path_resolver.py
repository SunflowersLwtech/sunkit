"""
Path Resolver
=============

Provides intelligent path resolution for storage locations.
Supports both project-level and global-level storage.
"""

import hashlib
import os
from pathlib import Path
from typing import Literal

from ..debug import server_debug_log as debug_log


def get_global_config_dir() -> Path:
    """
    Get the global configuration directory.

    On Windows: %APPDATA%/mcp-sidecar
    On Unix: ~/.config/mcp-sidecar

    Returns:
        Path to global config directory
    """
    if os.name == "nt":
        # Windows
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    else:
        # Unix-like
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))

    return Path(base) / "mcp-sidecar"


def get_project_hash(project_directory: str) -> str:
    """
    Generate a unique hash for a project directory.

    Args:
        project_directory: The project root directory

    Returns:
        A short hash identifying the project
    """
    normalized_path = str(Path(project_directory).resolve())
    return hashlib.md5(normalized_path.encode()).hexdigest()[:12]


def get_storage_path(
    project_directory: str | None = None,
    storage_type: Literal["sessions", "debug", "meta"] = "debug",
    use_global: bool = False,
) -> Path:
    """
    Get the appropriate storage path for a given storage type.

    Storage priority:
    1. Project-level (default): {project_root}/.mcp-sidecar/{type}/
    2. Global-level: ~/.config/mcp-sidecar/projects/{hash}/{type}/

    Args:
        project_directory: Project root directory (required if use_global=False)
        storage_type: Type of storage (sessions, debug, meta)
        use_global: If True, use global storage instead of project-level

    Returns:
        Path to the storage directory
    """
    if use_global or project_directory is None:
        # Global storage
        global_dir = get_global_config_dir()

        if project_directory:
            # Project-specific global storage
            project_hash = get_project_hash(project_directory)
            storage_path = global_dir / "projects" / project_hash / storage_type
        else:
            # Truly global (e.g., global concepts)
            storage_path = global_dir / "global"
    else:
        # Project-level storage (default)
        project_path = Path(project_directory).resolve()
        storage_path = project_path / ".mcp-sidecar" / storage_type

    # Ensure directory exists
    storage_path.mkdir(parents=True, exist_ok=True)

    debug_log(f"Storage path resolved: {storage_path}")
    return storage_path


def get_project_storage_path(project_directory: str) -> Path:
    """
    Get the project-level storage root.

    Args:
        project_directory: Project root directory

    Returns:
        Path to {project_root}/.mcp-sidecar/
    """
    project_path = Path(project_directory).resolve()
    storage_path = project_path / ".mcp-sidecar"
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


def get_global_storage_path() -> Path:
    """
    Get the global storage root.

    Returns:
        Path to ~/.config/mcp-sidecar/global/
    """
    storage_path = get_global_config_dir() / "global"
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


def resolve_storage_priority(
    project_directory: str,
    storage_type: Literal["sessions", "debug"] = "debug",
) -> tuple[Path, bool]:
    """
    Resolve storage path with priority.

    Checks project-level first, falls back to global.

    Args:
        project_directory: Project root directory
        storage_type: Type of storage

    Returns:
        Tuple of (storage_path, is_project_level)
    """
    # Try project-level first
    project_path = get_storage_path(
        project_directory=project_directory,
        storage_type=storage_type,
        use_global=False,
    )

    # Check if it has data
    if project_path.exists() and any(project_path.iterdir()):
        return project_path, True

    # Check global
    global_path = get_storage_path(
        project_directory=project_directory,
        storage_type=storage_type,
        use_global=True,
    )

    if global_path.exists() and any(global_path.iterdir()):
        return global_path, False

    # Default to project-level
    return project_path, True
