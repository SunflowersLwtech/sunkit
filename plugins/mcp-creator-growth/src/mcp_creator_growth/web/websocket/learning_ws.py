"""
Learning WebSocket Service
==========================

Handles real-time communication between the learning UI and the server.
Pushes session data updates to connected clients.
"""

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ...debug import web_debug_log as debug_log


class LearningWebSocket:
    """
    WebSocket manager for learning sessions.

    Handles:
    - Client connections
    - Session data broadcasting
    - Quiz answer submissions
    - Real-time updates
    """

    def __init__(self):
        """Initialize the WebSocket manager."""
        # Map of session_id -> list of connected WebSocket clients
        self.active_connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """
        Accept a WebSocket connection for a session.

        Args:
            websocket: The WebSocket connection
            session_id: The session ID to connect to
        """
        await websocket.accept()

        async with self._lock:
            if session_id not in self.active_connections:
                self.active_connections[session_id] = []
            self.active_connections[session_id].append(websocket)

        debug_log(f"WebSocket connected for session: {session_id}")

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """
        Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove
            session_id: The session ID
        """
        async with self._lock:
            if session_id in self.active_connections:
                try:
                    self.active_connections[session_id].remove(websocket)
                    if not self.active_connections[session_id]:
                        del self.active_connections[session_id]
                except ValueError:
                    pass

        debug_log(f"WebSocket disconnected for session: {session_id}")

    async def broadcast_to_session(self, session_id: str, message: dict[str, Any]) -> None:
        """
        Broadcast a message to all clients connected to a session.

        Args:
            session_id: The session ID
            message: The message to broadcast
        """
        async with self._lock:
            connections = self.active_connections.get(session_id, []).copy()

        if not connections:
            debug_log(f"No connections for session: {session_id}")
            return

        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                debug_log(f"Failed to send to websocket: {e}")
                disconnected.append(websocket)

        # Clean up disconnected clients
        for ws in disconnected:
            await self.disconnect(ws, session_id)

        debug_log(f"Broadcast to {len(connections)} clients for session: {session_id}")

    async def send_session_data(self, session_id: str, session_data: dict[str, Any]) -> None:
        """
        Send session data to all connected clients.

        Args:
            session_id: The session ID
            session_data: The session data to send
        """
        message = {
            "type": "session_data",
            "data": session_data,
        }
        await self.broadcast_to_session(session_id, message)

    async def send_quiz_result(self, session_id: str, result: dict[str, Any]) -> None:
        """
        Send quiz result to all connected clients.

        Args:
            session_id: The session ID
            result: The quiz result data
        """
        message = {
            "type": "quiz_result",
            "data": result,
        }
        await self.broadcast_to_session(session_id, message)

    async def send_notification(
        self,
        session_id: str,
        notification_type: str,
        content: str,
        severity: str = "info"
    ) -> None:
        """
        Send a notification to all connected clients.

        Args:
            session_id: The session ID
            notification_type: Type of notification
            content: Notification content
            severity: info, success, warning, or error
        """
        message = {
            "type": "notification",
            "notification_type": notification_type,
            "content": content,
            "severity": severity,
        }
        await self.broadcast_to_session(session_id, message)

    def get_connection_count(self, session_id: str) -> int:
        """Get the number of connections for a session."""
        return len(self.active_connections.get(session_id, []))

    def is_session_connected(self, session_id: str) -> bool:
        """Check if any clients are connected to a session."""
        return session_id in self.active_connections and len(self.active_connections[session_id]) > 0


# Global WebSocket manager instance
_websocket_manager: LearningWebSocket | None = None


def get_websocket_manager() -> LearningWebSocket:
    """Get the global WebSocket manager instance."""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = LearningWebSocket()
    return _websocket_manager


async def handle_websocket_connection(
    websocket: WebSocket,
    session_id: str,
    manager: "Any"  # WebUIManager
) -> None:
    """
    Handle a WebSocket connection for a learning session.

    Args:
        websocket: The WebSocket connection
        session_id: The session ID
        manager: The WebUIManager instance
    """
    ws_manager = get_websocket_manager()
    await ws_manager.connect(websocket, session_id)

    # Get the session
    session = manager.get_session(session_id)
    if session:
        # Store websocket reference in session
        session.websocket = websocket

        # Send initial session data
        await ws_manager.send_session_data(session_id, session.get_session_data())

    try:
        while True:
            # Receive and handle messages from client
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                await handle_client_message(websocket, session_id, message, manager)
            except json.JSONDecodeError:
                debug_log(f"Invalid JSON received: {data}")
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format",
                })

    except WebSocketDisconnect:
        debug_log(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        debug_log(f"WebSocket error: {e}")
    finally:
        await ws_manager.disconnect(websocket, session_id)
        if session:
            session.websocket = None


async def handle_client_message(
    websocket: WebSocket,
    session_id: str,
    message: dict[str, Any],
    manager: "Any"
) -> None:
    """
    Handle a message received from a client.

    Args:
        websocket: The WebSocket connection
        session_id: The session ID
        message: The parsed message
        manager: The WebUIManager instance
    """
    msg_type = message.get("type")

    if msg_type == "start_learning":
        # User started learning
        session = manager.get_session(session_id)
        if session:
            session.start_learning()
            await websocket.send_json({
                "type": "status",
                "status": "in_progress",
                "message": "Learning started",
            })

    elif msg_type == "submit_answer":
        # User submitted an answer
        question_index = message.get("question_index")
        answer = message.get("answer")
        debug_log(f"Answer submitted: Q{question_index} = {answer}")

        await websocket.send_json({
            "type": "answer_received",
            "question_index": question_index,
            "answer": answer,
        })

    elif msg_type == "complete_learning":
        # User completed learning
        answers = message.get("answers", [])
        score = message.get("score", 0)

        session = manager.get_session(session_id)
        if session and session.is_active():
            await session.submit_learning_result(answers, score)
            await websocket.send_json({
                "type": "status",
                "status": "completed",
                "message": "Learning completed",
                "score": score,
            })
        else:
            await websocket.send_json({
                "type": "error",
                "message": "Session not found or not active",
            })

    elif msg_type == "cancel":
        # User cancelled learning
        session = manager.get_session(session_id)
        if session:
            session.cancel()
            await websocket.send_json({
                "type": "status",
                "status": "cancelled",
                "message": "Learning cancelled",
            })

    elif msg_type == "ping":
        # Keep-alive ping
        await websocket.send_json({"type": "pong"})

    else:
        debug_log(f"Unknown message type: {msg_type}")
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown message type: {msg_type}",
        })
