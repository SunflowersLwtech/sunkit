"""
Constants for MCP Learning Sidecar web module.
"""

MESSAGE_CODES = {
    "SESSION_CREATED": "MSG_SESSION_CREATED",
    "SESSION_COMPLETED": "MSG_SESSION_COMPLETED",
    "LEARNING_SUBMITTED": "MSG_LEARNING_SUBMITTED",
    "TIMEOUT_CLEANUP": "MSG_TIMEOUT_CLEANUP",
    "SESSION_NOT_FOUND": "MSG_SESSION_NOT_FOUND",
    "INVALID_REQUEST": "MSG_INVALID_REQUEST",
}


def get_message_code(key: str) -> str:
    """Get message code by key."""
    return MESSAGE_CODES.get(key, f"MSG_{key.upper()}")
