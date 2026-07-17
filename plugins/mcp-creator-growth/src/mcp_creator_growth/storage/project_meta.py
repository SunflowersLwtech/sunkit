"""
Project Meta Manager
====================

Manages project-level metadata stored in meta.json.
Tracks project information, learning progress, and statistics.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from ..debug import server_debug_log as debug_log
from .path_resolver import get_project_storage_path, get_project_hash
from .serializers import load_json_file, save_json_file


class ProjectMetaManager:
    """
    Manages project metadata.

    Storage location: {project_root}/.mcp-sidecar/meta.json

    Metadata includes:
    - Project hash and name
    - Learning statistics
    - Debug statistics
    - Last activity timestamps
    """

    def __init__(self, project_directory: str):
        """
        Initialize the project meta manager.

        Args:
            project_directory: The project root directory
        """
        self.project_directory = Path(project_directory).resolve()
        self.storage_dir = get_project_storage_path(str(self.project_directory))
        self.meta_file = self.storage_dir / "meta.json"
        self.project_hash = get_project_hash(str(self.project_directory))

        # Load or create metadata
        self._meta = self._load_meta()

        debug_log(f"Project meta manager initialized for {self.project_directory}")

    def _load_meta(self) -> dict[str, Any]:
        """Load metadata or create new one."""
        data = load_json_file(self.meta_file)
        if data:
            return data

        # Create default metadata
        project_name = self.project_directory.name

        return {
            "version": 1,
            "project_hash": self.project_hash,
            "project_name": project_name,
            "project_path": str(self.project_directory),
            "created_at": datetime.now().isoformat(),
            "statistics": {
                "learning_sessions": 0,
                "debug_records": 0,
                "total_quiz_score": 0,
                "total_learning_time": 0,
            },
            "last_learning_session": None,
            "last_debug_record": None,
        }

    def _save_meta(self) -> None:
        """Save metadata to file."""
        self._meta["updated_at"] = datetime.now().isoformat()
        save_json_file(self.meta_file, self._meta)

    def get_project_hash(self) -> str:
        """Get the project hash."""
        return self.project_hash

    def get_project_name(self) -> str:
        """Get the project name."""
        return self._meta.get("project_name", self.project_directory.name)

    def set_project_name(self, name: str) -> None:
        """Set the project name."""
        self._meta["project_name"] = name
        self._save_meta()

    def record_learning_session(
        self,
        session_id: str,
        quiz_score: int,
        learning_time: float,
    ) -> None:
        """
        Record a completed learning session.

        Args:
            session_id: The session ID
            quiz_score: Quiz score achieved
            learning_time: Time spent learning (seconds)
        """
        stats = self._meta["statistics"]
        stats["learning_sessions"] += 1
        stats["total_quiz_score"] += quiz_score
        stats["total_learning_time"] += learning_time

        self._meta["last_learning_session"] = {
            "session_id": session_id,
            "quiz_score": quiz_score,
            "learning_time": learning_time,
            "completed_at": datetime.now().isoformat(),
        }

        self._save_meta()
        debug_log(f"Recorded learning session: {session_id}")

    def record_debug_entry(self, record_id: str) -> None:
        """
        Record a new debug entry.

        Args:
            record_id: The debug record ID
        """
        stats = self._meta["statistics"]
        stats["debug_records"] += 1

        self._meta["last_debug_record"] = {
            "record_id": record_id,
            "recorded_at": datetime.now().isoformat(),
        }

        self._save_meta()
        debug_log(f"Recorded debug entry: {record_id}")

    def get_statistics(self) -> dict[str, Any]:
        """Get project statistics."""
        return self._meta.get("statistics", {}).copy()

    def get_last_learning_session(self) -> dict[str, Any] | None:
        """Get last learning session info."""
        return self._meta.get("last_learning_session")

    def get_last_debug_record(self) -> dict[str, Any] | None:
        """Get last debug record info."""
        return self._meta.get("last_debug_record")

    def get_average_quiz_score(self) -> float:
        """Get average quiz score across all sessions."""
        stats = self._meta.get("statistics", {})
        sessions = stats.get("learning_sessions", 0)
        if sessions == 0:
            return 0.0
        return stats.get("total_quiz_score", 0) / sessions

    def get_total_learning_time(self) -> float:
        """Get total learning time in seconds."""
        return self._meta.get("statistics", {}).get("total_learning_time", 0)

    def get_metadata(self) -> dict[str, Any]:
        """Get all metadata."""
        return self._meta.copy()

    def update_metadata(self, **kwargs: Any) -> None:
        """
        Update metadata fields.

        Args:
            **kwargs: Fields to update
        """
        for key, value in kwargs.items():
            if key not in ("version", "created_at", "project_hash"):
                self._meta[key] = value

        self._save_meta()

    def reset_statistics(self) -> None:
        """Reset all statistics (use with caution)."""
        self._meta["statistics"] = {
            "learning_sessions": 0,
            "debug_records": 0,
            "total_quiz_score": 0,
            "total_learning_time": 0,
        }
        self._meta["last_learning_session"] = None
        self._meta["last_debug_record"] = None
        self._save_meta()
        debug_log("Reset project statistics")
