"""
Learning Session Model
======================

Manages learning session state with threading.Event-based blocking mechanism.
This is the core component that enables blocking the Agent until the user completes learning.
"""

import asyncio
import threading
import time
from enum import Enum
from typing import Any, Callable, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    pass

from fastapi import WebSocket

from ...debug import web_debug_log as debug_log


class LearningStatus(Enum):
    """Learning session status enumeration."""
    WAITING = "waiting"           # Waiting for user to start learning
    IN_PROGRESS = "in_progress"   # User is learning
    COMPLETED = "completed"       # User completed learning
    TIMEOUT = "timeout"           # Session timed out
    CANCELLED = "cancelled"       # User cancelled


class LearningSession:
    """
    Learning session management with blocking wait mechanism.

    Core mechanism:
    1. MCP tool call creates a session
    2. Session waits on threading.Event
    3. User completes learning in WebUI
    4. WebUI calls submit API which sets the Event
    5. wait_for_completion() returns, MCP tool completes
    """

    def __init__(
        self,
        session_id: str,
        project_directory: str,
        summary: str,
        reasoning: dict[str, Any] | None = None,
        quizzes: list[dict[str, Any]] | None = None,
        focus_areas: Sequence[str] | None = None,
        terms: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
        on_complete_callback: "Callable[[LearningSession], None] | None" = None,
    ):
        """
        Initialize a learning session.

        Args:
            session_id: Unique session identifier
            project_directory: Project directory for context
            summary: Summary of Agent's work
            reasoning: 5-Why reasoning structure (goal, trigger, mechanism, alternatives, risks)
            quizzes: List of quiz questions
            focus_areas: Learning focus areas
            terms: Programming terms to display (1-5 terms, auto-fetched if None)
            warnings: Warning codes to surface in the UI
            on_complete_callback: Optional callback to invoke on session completion (for persistence)
        """
        self.session_id = session_id
        self.project_directory = project_directory
        self.summary = summary
        self.reasoning = reasoning or self._generate_default_reasoning(summary)
        self.quizzes = quizzes or []
        self.focus_areas = list(focus_areas) if focus_areas else ["logic"]
        self.terms = terms or []
        self.warnings = warnings or []

        # Status tracking
        self.status = LearningStatus.WAITING
        self.created_at = time.time()
        self.start_time: float = 0
        self.end_time: float = 0

        # Blocking mechanism - this is the key!
        self.learning_completed = threading.Event()

        # Learning results (answers can be any format)
        self.quiz_answers: list[Any] = []
        self.quiz_score: int = 0

        # WebSocket for real-time communication
        self.websocket: WebSocket | None = None
        
        # Persistence callback
        self._on_complete_callback = on_complete_callback

        debug_log(f"Learning session {self.session_id} initialized")


    def _generate_default_reasoning(self, summary: str) -> dict[str, Any]:
        """Generate default reasoning structure."""
        return {
            "goal": f"Understanding: {summary[:100]}...",
            "trigger": "User requested learning session",
            "mechanism": "Code changes and their implications",
            "alternatives": "Could review code directly without quiz",
            "risks": "May miss important implementation details"
        }

    async def wait_for_completion(self, timeout: int = 600) -> dict[str, Any]:
        """
        Block and wait for user to complete learning.

        This is the core blocking mechanism that prevents the Agent
        from continuing until the user finishes the learning session.

        Args:
            timeout: Maximum wait time in seconds (default: 600 = 10 minutes)

        Returns:
            dict: Learning result containing status, score, and duration

        Raises:
            TimeoutError: If user doesn't complete within timeout
        """
        debug_log(f"Session {self.session_id} waiting for completion (timeout: {timeout}s)")

        # Use slightly shorter timeout to handle gracefully before MCP timeout
        actual_timeout = max(timeout - 5, 5) if timeout > 30 else max(timeout - 1, 5)

        loop = asyncio.get_event_loop()

        def wait_in_thread() -> bool:
            """Execute blocking wait in a thread to not block the event loop."""
            return self.learning_completed.wait(actual_timeout)

        # Run the blocking wait in a thread pool executor
        completed = await loop.run_in_executor(None, wait_in_thread)

        if completed:
            debug_log(f"Session {self.session_id} completed by user")
            return {
                "status": "completed",
                "score": self.quiz_score,
                "duration": self.end_time - self.start_time if self.start_time else 0,
                "answers": self.quiz_answers,
                "session_id": self.session_id,
            }
        else:
            self.status = LearningStatus.TIMEOUT
            debug_log(f"Session {self.session_id} timeout after {actual_timeout}s")
            raise TimeoutError(f"Learning session timeout ({actual_timeout} seconds)")

    async def submit_learning_result(
        self,
        answers: list[Any],
        score: int,
    ) -> None:
        """
        Submit learning result and unblock the waiting Agent.

        This is called when the user clicks "Complete Learning" in the WebUI.
        It sets the threading.Event which unblocks wait_for_completion().

        Args:
            answers: User's quiz answers (can be any format)
            score: Quiz score
        """
        self.quiz_answers = list(answers) if answers else []
        self.quiz_score = score
        self.end_time = time.time()
        self.status = LearningStatus.COMPLETED

        debug_log(f"Session {self.session_id} submitted: score={score}, answers={len(answers)}")

        # Invoke persistence callback if set
        if self._on_complete_callback:
            try:
                self._on_complete_callback(self)
            except Exception as e:
                debug_log(f"Persistence callback error: {e}")

        # This is the key: set the Event to unblock wait_for_completion()
        self.learning_completed.set()

    def start_learning(self) -> None:
        """Mark that user has started learning."""
        self.start_time = time.time()
        self.status = LearningStatus.IN_PROGRESS
        debug_log(f"Session {self.session_id} started learning")

    def cancel(self) -> None:
        """Cancel the learning session."""
        self.status = LearningStatus.CANCELLED
        self.end_time = time.time()
        self.learning_completed.set()  # Unblock the wait
        debug_log(f"Session {self.session_id} cancelled")

    def get_session_data(self) -> dict[str, Any]:
        """Get session data for WebUI rendering."""
        return {
            "session_id": self.session_id,
            "project_directory": self.project_directory,
            "summary": self.summary,
            "reasoning": self.reasoning,
            "quizzes": self.quizzes,
            "focus_areas": self.focus_areas,
            "terms": self.terms,
            "warnings": self.warnings,
            "status": self.status.value,
            "created_at": self.created_at,
        }

    def is_active(self) -> bool:
        """Check if session is still active (waiting or in progress)."""
        return self.status in [LearningStatus.WAITING, LearningStatus.IN_PROGRESS]

    def is_completed(self) -> bool:
        """Check if session has been completed."""
        return self.status == LearningStatus.COMPLETED

    def get_elapsed_time(self) -> float:
        """Get elapsed time since session started."""
        if self.start_time:
            end = self.end_time if self.end_time else time.time()
            return end - self.start_time
        return 0.0
