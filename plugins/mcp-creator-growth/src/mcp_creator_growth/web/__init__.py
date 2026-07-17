"""
Web module for MCP Learning Sidecar.
Provides WebUI management, routes, and WebSocket services.
"""

from .main import WebUIManager, get_web_ui_manager, launch_learning_session_ui

__all__ = ["WebUIManager", "get_web_ui_manager", "launch_learning_session_ui"]
