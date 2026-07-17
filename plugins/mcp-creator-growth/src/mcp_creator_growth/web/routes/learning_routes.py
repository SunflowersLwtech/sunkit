"""
Learning Routes
===============

FastAPI endpoints for learning session management.
Handles session data retrieval and learning result submission.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from ...debug import web_debug_log as debug_log

router = APIRouter(prefix="/api/learning", tags=["learning"])


class LearningSubmitRequest(BaseModel):
    """Request model for submitting learning results."""
    session_id: str | None = Field(default=None, description="Session ID")
    answers: list[Any] | None = Field(default=None, description="Quiz answers (list of any)")
    score: int | None = Field(default=None, description="Quiz score")
    duration: float | None = Field(default=None, description="Time spent in seconds")

    model_config = {"extra": "forbid"}

    @model_validator(mode="before")
    @classmethod
    def check_not_empty(cls, data: Any) -> Any:
        """Ensure payload is not empty and has at least one valid field."""
        if isinstance(data, dict):
            if not data:
                raise ValueError("Empty payload not allowed")
            recognized_fields = {"session_id", "answers", "score", "duration"}
            if not any(key in recognized_fields for key in data.keys()):
                raise ValueError("Payload must contain at least one valid field")
        return data


class LearningSubmitResponse(BaseModel):
    """Response model for learning submission."""
    success: bool
    message: str
    session_id: str


class SessionDataResponse(BaseModel):
    """Response model for session data."""
    session_id: str
    project_directory: str
    summary: str
    reasoning: dict[str, Any]
    quizzes: list[dict[str, Any]]
    focus_areas: list[str]
    terms: list[dict[str, Any]] = []
    warnings: list[str] = []
    status: str


# Session manager reference (will be set by main.py)
_session_manager = None


def set_session_manager(manager: Any) -> None:
    """Set the session manager reference."""
    global _session_manager
    _session_manager = manager


def get_session_manager() -> Any:
    """Get the session manager."""
    if _session_manager is None:
        raise HTTPException(status_code=500, detail="Session manager not initialized")
    return _session_manager


@router.post("/submit", response_model=LearningSubmitResponse)
async def submit_learning_result(request: LearningSubmitRequest) -> LearningSubmitResponse:
    """
    Submit learning result and unblock the waiting Agent.

    This endpoint is called when the user clicks "Complete Learning" in the WebUI.
    It triggers the threading.Event.set() which unblocks the MCP tool.
    """
    debug_log(f"Received learning submission for session: {request.session_id}")

    manager = get_session_manager()

    # Get session by ID, or use current session
    session_id = request.session_id
    if session_id:
        session = manager.get_session(session_id)
    else:
        session = manager.get_current_session()
        if session:
            session_id = session.session_id

    if session is None:
        debug_log(f"Session not found: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.is_active():
        debug_log(f"Session not active: {session_id}, status={session.status}")
        raise HTTPException(status_code=400, detail="Session is not active")

    try:
        answers = request.answers if request.answers is not None else []
        score = request.score if request.score is not None else 0

        await session.submit_learning_result(
            answers=answers,
            score=score,
        )

        debug_log(f"Learning submission successful: {session_id}")

        return LearningSubmitResponse(
            success=True,
            message="Learning completed successfully",
            session_id=session_id or "",
        )

    except Exception as e:
        debug_log(f"Error submitting learning result: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}", response_model=SessionDataResponse)
async def get_session_data(session_id: str) -> SessionDataResponse:
    """
    Get session data for WebUI rendering.

    Returns all the data needed to render the learning card:
    summary, reasoning, quizzes, and focus areas.
    """
    debug_log(f"Getting session data: {session_id}")

    manager = get_session_manager()
    session = manager.get_session(session_id)

    if session is None:
        debug_log(f"Session not found: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")

    data = session.get_session_data()

    return SessionDataResponse(
        session_id=data["session_id"],
        project_directory=data["project_directory"],
        summary=data["summary"],
        reasoning=data["reasoning"],
        quizzes=data["quizzes"],
        focus_areas=data["focus_areas"],
        terms=data.get("terms", []),
        warnings=data.get("warnings", []),
        status=data["status"],
    )


@router.post("/session/{session_id}/start")
async def start_learning(session_id: str) -> dict[str, Any]:
    """
    Mark that user has started learning.

    Called when the user opens the learning card and begins reading.
    """
    debug_log(f"Starting learning: {session_id}")

    manager = get_session_manager()
    session = manager.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session.start_learning()

    return {
        "success": True,
        "message": "Learning started",
        "session_id": session_id,
    }


@router.post("/session/{session_id}/cancel")
async def cancel_session(session_id: str) -> dict[str, Any]:
    """
    Cancel a learning session.

    Called when user decides to skip learning.
    This unblocks the Agent but with cancelled status.
    """
    debug_log(f"Cancelling session: {session_id}")

    manager = get_session_manager()
    session = manager.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session.cancel()

    return {
        "success": True,
        "message": "Session cancelled",
        "session_id": session_id,
    }


@router.get("/current")
async def get_current_session() -> dict[str, Any]:
    """
    Get the current active session.

    Returns the most recent active session if available.
    """
    manager = get_session_manager()
    session = manager.get_current_session()

    if session is None:
        return {
            "has_session": False,
            "session_id": None,
        }

    return {
        "has_session": True,
        "session_id": session.session_id,
        "status": session.status.value,
        "data": session.get_session_data(),
    }
