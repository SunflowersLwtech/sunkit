"""
Configuration Manager
=====================

Loads and manages configuration from TOML file and environment variables.
Configuration priority: Environment Variables > config.toml > Defaults
"""

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .debug import server_debug_log as debug_log

# Try to import tomllib (Python 3.11+) or tomli as fallback
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "127.0.0.1"
    port: int = 0  # 0 = auto-select
    log_level: str = "warning"


@dataclass
class StorageConfig:
    """Storage configuration."""
    use_global: bool = False  # Default to project-level storage
    sessions_enabled: bool = True
    max_session_history: int = 100


@dataclass
class UIConfig:
    """UI configuration."""
    theme: str = "auto"  # auto, dark, light
    language: str = "en"  # en, zh-CN, zh-TW
    show_keyboard_hints: bool = True


@dataclass
class SessionConfig:
    """Session configuration."""
    default_timeout: int = 600  # 10 minutes
    auto_save: bool = True
    save_answers: bool = True


@dataclass
class Config:
    """Main configuration container."""
    server: ServerConfig = field(default_factory=ServerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    session: SessionConfig = field(default_factory=SessionConfig)


def get_config_path() -> Path:
    """Get the path to the global config file."""
    if os.name == "nt":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    
    return Path(base) / "mcp-sidecar" / "config.toml"


def _load_toml_file(path: Path) -> dict[str, Any]:
    """Load a TOML file and return its contents."""
    if not path.exists():
        debug_log(f"Config file not found: {path}")
        return {}
    
    if tomllib is None:
        warning_message = (
            "TOML parser not available; config file will be ignored. "
            "Install 'tomli' for Python < 3.11."
        )
        warnings.warn(warning_message, RuntimeWarning)
        debug_log(warning_message)
        return {}
    
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
            debug_log(f"Loaded config from: {path}")
            return data
    except Exception as e:
        debug_log(f"Error loading config: {e}")
        return {}


def _get_env_value(key: str, default: Any = None) -> Any:
    """Get environment variable with type conversion."""
    env_key = f"MCP_SIDECAR_{key.upper().replace('.', '_')}"
    value = os.environ.get(env_key)
    
    if value is None:
        return default
    
    # Type conversion based on default type
    if isinstance(default, bool):
        return value.lower() in ("true", "1", "yes", "on")
    elif isinstance(default, int):
        try:
            return int(value)
        except ValueError:
            return default
    
    return value


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration with priority: Environment > TOML > Defaults.
    
    Args:
        config_path: Optional path to config file. Uses default if not provided.
        
    Returns:
        Loaded Config object
    """
    path = config_path or get_config_path()
    toml_data = _load_toml_file(path)
    
    # Server config
    server_data = toml_data.get("server", {})
    server = ServerConfig(
        host=_get_env_value("server.host", server_data.get("host", "127.0.0.1")),
        port=_get_env_value("server.port", server_data.get("port", 0)),
        log_level=_get_env_value("server.log_level", server_data.get("log_level", "warning")),
    )
    
    # Storage config
    storage_data = toml_data.get("storage", {})
    storage = StorageConfig(
        use_global=_get_env_value("storage.use_global", storage_data.get("use_global", False)),
        sessions_enabled=_get_env_value("storage.sessions_enabled", storage_data.get("sessions_enabled", True)),
        max_session_history=_get_env_value("storage.max_session_history", storage_data.get("max_session_history", 100)),
    )
    
    # UI config
    ui_data = toml_data.get("ui", {})
    ui = UIConfig(
        theme=_get_env_value("ui.theme", ui_data.get("theme", "auto")),
        language=_get_env_value("ui.language", ui_data.get("language", "en")),
        show_keyboard_hints=_get_env_value("ui.show_keyboard_hints", ui_data.get("show_keyboard_hints", True)),
    )
    
    # Session config
    session_data = toml_data.get("session", {})
    session = SessionConfig(
        default_timeout=_get_env_value("session.default_timeout", session_data.get("default_timeout", 600)),
        auto_save=_get_env_value("session.auto_save", session_data.get("auto_save", True)),
        save_answers=_get_env_value("session.save_answers", session_data.get("save_answers", True)),
    )
    
    return Config(
        server=server,
        storage=storage,
        ui=ui,
        session=session,
    )


def create_default_config(path: Path | None = None) -> Path:
    """
    Create a default config.toml file.
    
    Args:
        path: Optional path. Uses default if not provided.
        
    Returns:
        Path to created config file
    """
    config_path = path or get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    default_content = '''# MCP Learning Sidecar Configuration
# Location: ~/.config/mcp-sidecar/config.toml (Unix) or %APPDATA%/mcp-sidecar/config.toml (Windows)

[server]
# Server host and port (0 = auto-select port)
host = "127.0.0.1"
port = 0
log_level = "warning"  # debug, info, warning, error

[storage]
# Use global storage instead of project-level
use_global = false
# Enable session persistence
sessions_enabled = true
# Maximum number of sessions to keep in history
max_session_history = 100

[ui]
# Theme: auto, dark, light
theme = "auto"
# Language: en, zh-CN, zh-TW
language = "en"
# Show keyboard shortcut hints
show_keyboard_hints = true

[session]
# Default timeout for learning sessions (seconds)
default_timeout = 600
# Auto-save session on completion
auto_save = true
# Save quiz answers in session data
save_answers = true
'''
    
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(default_content)
    
    debug_log(f"Created default config at: {config_path}")
    return config_path


# Global config instance (lazy loaded)
_config: Config | None = None


def get_config() -> Config:
    """Get the global config instance (lazy loaded)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> Config:
    """Reload config from file."""
    global _config
    _config = load_config()
    return _config
