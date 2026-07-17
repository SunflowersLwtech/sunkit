"""
Debug logging utilities for MCP Learning Sidecar.
"""

import os
import sys
from datetime import datetime


def _is_debug_enabled() -> bool:
    """Check if debug mode is enabled."""
    return os.getenv("MCP_DEBUG", "").lower() in ("true", "1", "yes", "on")


def debug_log(message: str) -> None:
    """Log debug message to stderr."""
    if _is_debug_enabled():
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {message}", file=sys.stderr)


def server_debug_log(message: str) -> None:
    """Server-specific debug logging."""
    debug_log(f"[SERVER] {message}")


def web_debug_log(message: str) -> None:
    """Web-specific debug logging."""
    debug_log(f"[WEB] {message}")
