"""
Web UI Manager
==============

Manages the FastAPI server, learning sessions, and browser integration.
"""

import asyncio
import socket
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Sequence

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from ..debug import web_debug_log as debug_log
from ..config import get_config
from ..storage import SessionStorageManager
from .models.learning_session import LearningSession
from .routes.learning_routes import router as learning_router, set_session_manager
from .websocket.learning_ws import handle_websocket_connection


# Global instance
_web_ui_manager: "WebUIManager | None" = None


def get_web_ui_manager() -> "WebUIManager":
    """Get the global WebUIManager instance."""
    global _web_ui_manager
    if _web_ui_manager is None:
        _web_ui_manager = WebUIManager()
    return _web_ui_manager


class WebUIManager:
    """
    Manages the Web UI server and learning sessions.

    Responsibilities:
    - Start/stop FastAPI server
    - Manage learning sessions
    - Handle browser opening
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        """
        Initialize the WebUIManager.

        Args:
            host: Server host address
            port: Server port (0 = auto-select)
        """
        self.host = host
        self.port = port if port > 0 else self._find_available_port()
        self._app: FastAPI | None = None
        self.server_thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None

        # Session management
        self.sessions: dict[str, LearningSession] = {}
        self.current_session_id: str | None = None
        
        # Session storage managers (lazy initialized per project)
        self._session_storage: dict[str, SessionStorageManager] = {}

        debug_log(f"WebUIManager initialized: {self.host}:{self.port}")

    @property
    def app(self) -> FastAPI:
        """Get the FastAPI app, creating it if necessary."""
        if self._app is None:
            self._app = self._create_app()
        return self._app

    def _find_available_port(self, start: int = 8765, end: int = 8865) -> int:
        """Find an available port in the specified range."""
        for port in range(start, end):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind((self.host, port))
                    return port
            except OSError:
                continue
        raise RuntimeError(f"No available ports in range {start}-{end}")

    def _create_app(self) -> FastAPI:
        """Create and configure the FastAPI application."""
        app = FastAPI(
            title="MCP Learning Sidecar",
            description="Learning session management for AI coding assistants",
            version="1.0.0",
        )

        # Register routes
        app.include_router(learning_router)

        # Set session manager reference for routes
        set_session_manager(self)

        # Mount static files
        static_dir = Path(__file__).parent / "static" / "learning"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        # Root endpoint - serve test page
        @app.get("/", response_class=HTMLResponse)
        async def root():
            return self._get_test_page_html()

        # Learning page endpoint
        @app.get("/learning", response_class=HTMLResponse)
        async def learning_page():
            return self._get_test_page_html()

        # Health check
        @app.get("/health")
        async def health():
            return {
                "status": "healthy",
                "sessions_count": len(self.sessions),
                "current_session": self.current_session_id,
            }

        # Learning status endpoint
        @app.get("/api/learning/status")
        async def learning_status():
            current = self.get_current_session()
            has_active = current is not None and current.is_active()
            return {
                "has_session": current is not None,
                "has_active_session": has_active,
                "active": has_active,
                "session_id": current.session_id if current else None,
                "status": current.status.value if current else None,
            }

        # WebSocket endpoint for real-time communication
        @app.websocket("/ws/learning/{session_id}")
        async def websocket_endpoint(websocket: WebSocket, session_id: str):
            await handle_websocket_connection(websocket, session_id, self)

        return app

    def _get_test_page_html(self) -> str:
        """Get the test page HTML content."""
        static_file = Path(__file__).parent / "static" / "learning" / "test.html"
        if static_file.exists():
            return static_file.read_text(encoding="utf-8")

        # Fallback inline HTML
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>MCP Learning Sidecar - Test</title>
            <meta charset="utf-8">
            <style>
                body { font-family: system-ui; max-width: 800px; margin: 50px auto; padding: 20px; }
                .card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin: 20px 0; }
                button { padding: 10px 20px; font-size: 16px; cursor: pointer; }
                .success { background: #d4edda; border-color: #c3e6cb; }
                .error { background: #f8d7da; border-color: #f5c6cb; }
            </style>
        </head>
        <body>
            <h1>MCP Learning Sidecar - Test Page</h1>
            <div class="card" id="status-card">
                <h2>Session Status</h2>
                <p id="status">Loading...</p>
            </div>
            <div class="card">
                <h2>Actions</h2>
                <button onclick="submitLearning()">Complete Learning</button>
                <button onclick="cancelSession()">Cancel</button>
            </div>
            <script>
                async function loadSession() {
                    try {
                        const resp = await fetch('/api/learning/current');
                        const data = await resp.json();
                        if (data.has_session) {
                            document.getElementById('status').textContent =
                                `Session: ${data.session_id} (${data.status})`;
                            window.currentSessionId = data.session_id;
                        } else {
                            document.getElementById('status').textContent = 'No active session';
                        }
                    } catch (e) {
                        document.getElementById('status').textContent = 'Error: ' + e.message;
                    }
                }
                async function submitLearning() {
                    if (!window.currentSessionId) {
                        alert('No active session');
                        return;
                    }
                    try {
                        const resp = await fetch('/api/learning/submit', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                session_id: window.currentSessionId,
                                answers: [{question: 1, answer: 'A'}],
                                score: 3
                            })
                        });
                        const data = await resp.json();
                        document.getElementById('status-card').classList.add('success');
                        document.getElementById('status').textContent = 'Submitted! ' + data.message;
                    } catch (e) {
                        document.getElementById('status-card').classList.add('error');
                        document.getElementById('status').textContent = 'Error: ' + e.message;
                    }
                }
                async function cancelSession() {
                    if (!window.currentSessionId) return;
                    await fetch(`/api/learning/session/${window.currentSessionId}/cancel`, {method: 'POST'});
                    loadSession();
                }
                loadSession();
            </script>
        </body>
        </html>
        """

    def create_learning_session(
        self,
        project_directory: str,
        summary: str,
        reasoning: dict[str, Any] | None = None,
        quizzes: list[dict[str, Any]] | None = None,
        focus_areas: Sequence[str] | None = None,
        terms: list[dict[str, Any]] | None = None,
    ) -> LearningSession:
        """
        Create a new learning session.

        Args:
            project_directory: Project directory
            summary: Summary of Agent's work
            reasoning: 5-Why reasoning structure
            quizzes: Quiz questions
            focus_areas: Learning focus areas
            terms: Programming terms to display (auto-fetched if None)

        Returns:
            The created LearningSession
        """
        session_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"

        # Get or create session storage for this project
        config = get_config()
        storage = None
        session_warnings: list[str] = []
        if config.storage.sessions_enabled:
            if project_directory not in self._session_storage:
                try:
                    self._session_storage[project_directory] = SessionStorageManager(project_directory)
                except Exception as e:
                    debug_log(f"Failed to init session storage: {e}")
                    session_warnings.append("sessionStorageUnavailable")
            storage = self._session_storage.get(project_directory)
            if storage is None and "sessionStorageUnavailable" not in session_warnings:
                session_warnings.append("sessionStorageUnavailable")

        # Auto-fetch terms if not provided
        if terms is None:
            try:
                from ..storage import get_session_terms
                terms = get_session_terms(project_directory, count=3, auto_mark=True)
                debug_log(f"Auto-fetched {len(terms)} terms for session")
            except Exception as e:
                debug_log(f"Failed to auto-fetch terms: {e}")
                terms = []

        # Create persistence callback
        def on_session_complete(session: LearningSession) -> None:
            if storage and config.session.auto_save:
                try:
                    storage.save_session(
                        session_id=session.session_id,
                        session_data=session.get_session_data(),
                        quiz_score=session.quiz_score,
                        time_spent=session.get_elapsed_time(),
                        answers=session.quiz_answers if config.session.save_answers else None,
                    )
                except Exception as e:
                    debug_log(f"Failed to save session: {e}")

        session = LearningSession(
            session_id=session_id,
            project_directory=project_directory,
            summary=summary,
            reasoning=reasoning,
            quizzes=quizzes,
            focus_areas=focus_areas,
            terms=terms,
            warnings=session_warnings,
            on_complete_callback=on_session_complete if storage else None,
        )

        self.sessions[session_id] = session
        self.current_session_id = session_id

        debug_log(f"Created learning session: {session_id}")

        return session

    def get_session(self, session_id: str) -> LearningSession | None:
        """Get a session by ID."""
        return self.sessions.get(session_id)

    def get_current_session(self) -> LearningSession | None:
        """Get the current active session."""
        if self.current_session_id:
            return self.sessions.get(self.current_session_id)
        return None

    def is_running(self) -> bool:
        """Check if the server is running."""
        return self.server_thread is not None and self.server_thread.is_alive()

    def start_server(self) -> None:
        """Start the FastAPI server in a background thread."""
        if self.is_running():
            debug_log("Server already running")
            return

        # Use the app property which creates the app if needed
        app = self.app

        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        def run_server():
            asyncio.run(self._server.serve())

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # Wait for server to start
        time.sleep(0.5)
        debug_log(f"Server started at {self.get_server_url()}")

    def stop_server(self) -> None:
        """Stop the FastAPI server."""
        if self._server:
            self._server.should_exit = True
            debug_log("Server stop requested")

    def get_server_url(self) -> str:
        """Get the server URL."""
        return f"http://{self.host}:{self.port}"

    async def smart_open_browser(self, url: str) -> None:
        """Open the browser with smart detection."""
        try:
            webbrowser.open(url)
            debug_log(f"Opened browser: {url}")
        except Exception as e:
            debug_log(f"Failed to open browser: {e}")


async def launch_learning_session_ui(
    project_directory: str,
    summary: str,
    reasoning: dict[str, Any] | None = None,
    quizzes: list[dict[str, Any]] | None = None,
    focus_areas: Sequence[str] | None = None,
    terms: list[dict[str, Any]] | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    """
    Launch the learning session UI and wait for completion.

    This is the main entry point called by the MCP tool.
    It creates a session, starts the server, opens the browser,
    and blocks until the user completes learning.

    Args:
        project_directory: Project directory
        summary: Summary of Agent's work
        reasoning: 5-Why reasoning structure
        quizzes: Quiz questions
        focus_areas: Learning focus areas
        terms: Programming terms to display (auto-fetched if None)
        timeout: Timeout in seconds

    Returns:
        dict: Learning result
    """
    manager = get_web_ui_manager()

    # Create session
    session = manager.create_learning_session(
        project_directory=project_directory,
        summary=summary,
        reasoning=reasoning,
        quizzes=quizzes,
        focus_areas=focus_areas,
        terms=terms,
    )

    # Start server if not running
    if not manager.is_running():
        manager.start_server()

    # Open browser
    url = f"{manager.get_server_url()}?session={session.session_id}"
    await manager.smart_open_browser(url)

    # Block and wait for completion
    try:
        result = await session.wait_for_completion(timeout)
        return result
    except TimeoutError as e:
        debug_log(f"Session timed out: {e}")
        raise
