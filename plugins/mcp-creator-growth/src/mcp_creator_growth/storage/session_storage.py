"""
Session Storage Manager
=======================

Manages persistence of learning sessions to disk.
Sessions are stored in {project}/.mcp-sidecar/sessions/
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from ..debug import server_debug_log as debug_log
from .path_resolver import get_storage_path
from .serializers import save_json_file, load_json_file
from .project_meta import ProjectMetaManager


class SessionStorageManager:
    """
    Manages learning session persistence.
    
    Storage structure:
    {project}/.mcp-sidecar/sessions/
    ├── index.json              # Session index for quick lookup
    ├── 20260118_abc123.json    # Individual session files
    └── 20260118_def456.json
    """
    
    def __init__(self, project_directory: str):
        """
        Initialize the session storage manager.
        
        Args:
            project_directory: The project root directory
        """
        self.project_directory = Path(project_directory).resolve()
        self.storage_dir = get_storage_path(
            project_directory=str(self.project_directory),
            storage_type="sessions",
            use_global=False,
        )
        self.index_file = self.storage_dir / "index.json"
        
        # Ensure storage directory exists
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Load or create index
        self._index = self._load_index()
        
        debug_log(f"Session storage initialized at: {self.storage_dir}")
    
    def _load_index(self) -> dict[str, Any]:
        """Load the session index or create a new one."""
        data = load_json_file(self.index_file)
        if data:
            return data
        
        return {
            "version": 1,
            "created_at": datetime.now().isoformat(),
            "sessions": [],
            "statistics": {
                "total_sessions": 0,
                "total_quiz_score": 0,
                "total_time_spent": 0,
            },
        }
    
    def _save_index(self) -> None:
        """Save the session index."""
        self._index["updated_at"] = datetime.now().isoformat()
        save_json_file(self.index_file, self._index)
    
    def save_session(
        self,
        session_id: str,
        session_data: dict[str, Any],
        quiz_score: int = 0,
        time_spent: float = 0,
        answers: list[Any] | None = None,
    ) -> str:
        """
        Save a completed learning session.
        
        Args:
            session_id: Unique session identifier
            session_data: Session data from LearningSession.get_session_data()
            quiz_score: Quiz score achieved
            time_spent: Time spent in seconds
            answers: Optional quiz answers
            
        Returns:
            Path to saved session file
        """
        timestamp = datetime.now()
        
        # Build session record
        record = {
            "session_id": session_id,
            "saved_at": timestamp.isoformat(),
            "project_directory": str(self.project_directory),
            "summary": session_data.get("summary", ""),
            "reasoning": session_data.get("reasoning", {}),
            "quizzes": session_data.get("quizzes", []),
            "focus_areas": session_data.get("focus_areas", []),
            "results": {
                "quiz_score": quiz_score,
                "time_spent": time_spent,
                "answers": answers or [],
            },
            "metadata": {
                "created_at": session_data.get("created_at", timestamp.isoformat()),
                "completed_at": timestamp.isoformat(),
            },
        }
        
        # Generate filename
        date_str = timestamp.strftime("%Y%m%d")
        short_id = session_id.split("_")[-1] if "_" in session_id else session_id[:8]
        filename = f"{date_str}_{short_id}.json"
        session_file = self.storage_dir / filename
        
        # Save session file
        save_json_file(session_file, record)
        
        # Update index with compact keys for token savings
        # Keys: sid=session_id, fn=filename, ts=saved_at, qs=quiz_score, t=time_spent, sp=summary_preview
        index_entry = {
            "sid": session_id,
            "fn": filename,
            "ts": timestamp.isoformat(),
            "qs": quiz_score,
            "t": time_spent,
            "sp": session_data.get("summary", "")[:50],  # Reduced preview length
        }
        self._index["sessions"].append(index_entry)
        
        # Update statistics
        stats = self._index["statistics"]
        stats["total_sessions"] += 1
        stats["total_quiz_score"] += quiz_score
        stats["total_time_spent"] += time_spent
        
        self._save_index()
        
        # Update project metadata
        try:
            meta_manager = ProjectMetaManager(str(self.project_directory))
            meta_manager.record_learning_session(session_id, quiz_score, time_spent)
        except Exception as e:
            debug_log(f"Failed to update project meta: {e}")
        
        debug_log(f"Session saved: {filename}")
        return str(session_file)
    
    def _get_entry_field(self, entry: dict, field: str, short: str, default: Any = None) -> Any:
        """Get field from entry, supporting both old and new key formats."""
        return entry.get(short) or entry.get(field, default)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """
        Load a session by ID.

        Args:
            session_id: The session ID to load

        Returns:
            Session data or None if not found
        """
        # Find in index (supports both old "session_id" and new "sid" keys)
        for entry in self._index["sessions"]:
            entry_sid = self._get_entry_field(entry, "session_id", "sid")
            if entry_sid == session_id:
                filename = self._get_entry_field(entry, "filename", "fn")
                session_file = self.storage_dir / filename
                return load_json_file(session_file)

        return None
    
    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        List recent sessions.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of session index entries (most recent first), normalized to full keys
        """
        sessions = self._index["sessions"][-limit:]
        sessions.reverse()  # Most recent first

        # Normalize to full keys for backward compatibility in API responses
        normalized = []
        for entry in sessions:
            normalized.append({
                "session_id": self._get_entry_field(entry, "session_id", "sid"),
                "filename": self._get_entry_field(entry, "filename", "fn"),
                "saved_at": self._get_entry_field(entry, "saved_at", "ts"),
                "quiz_score": self._get_entry_field(entry, "quiz_score", "qs", 0),
                "time_spent": self._get_entry_field(entry, "time_spent", "t", 0),
                "summary_preview": self._get_entry_field(entry, "summary_preview", "sp", ""),
            })
        return normalized
    
    def get_session_by_date(self, date: str) -> list[dict[str, Any]]:
        """
        Get all sessions for a specific date.

        Args:
            date: Date string in YYYYMMDD format

        Returns:
            List of sessions for that date (normalized keys)
        """
        results = []
        for entry in self._index["sessions"]:
            filename = self._get_entry_field(entry, "filename", "fn", "")
            if filename.startswith(date):
                results.append({
                    "session_id": self._get_entry_field(entry, "session_id", "sid"),
                    "filename": filename,
                    "saved_at": self._get_entry_field(entry, "saved_at", "ts"),
                    "quiz_score": self._get_entry_field(entry, "quiz_score", "qs", 0),
                    "time_spent": self._get_entry_field(entry, "time_spent", "t", 0),
                    "summary_preview": self._get_entry_field(entry, "summary_preview", "sp", ""),
                })
        return results
    
    def get_statistics(self) -> dict[str, Any]:
        """Get session statistics."""
        stats = self._index["statistics"].copy()
        
        # Calculate averages
        total = stats["total_sessions"]
        if total > 0:
            stats["average_score"] = stats["total_quiz_score"] / total
            stats["average_time"] = stats["total_time_spent"] / total
        else:
            stats["average_score"] = 0
            stats["average_time"] = 0
        
        return stats
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: The session ID to delete

        Returns:
            True if deleted, False if not found
        """
        for i, entry in enumerate(self._index["sessions"]):
            entry_sid = self._get_entry_field(entry, "session_id", "sid")
            if entry_sid == session_id:
                # Remove file
                filename = self._get_entry_field(entry, "filename", "fn")
                session_file = self.storage_dir / filename
                if session_file.exists():
                    session_file.unlink()

                # Update statistics (support both key formats)
                stats = self._index["statistics"]
                stats["total_sessions"] -= 1
                stats["total_quiz_score"] -= self._get_entry_field(entry, "quiz_score", "qs", 0)
                stats["total_time_spent"] -= self._get_entry_field(entry, "time_spent", "t", 0)

                # Remove from index
                self._index["sessions"].pop(i)
                self._save_index()

                debug_log(f"Session deleted: {session_id}")
                return True

        return False
    
    def cleanup_old_sessions(self, max_sessions: int = 100) -> int:
        """
        Remove old sessions if exceeding max limit.

        Args:
            max_sessions: Maximum number of sessions to keep

        Returns:
            Number of sessions deleted
        """
        sessions = self._index["sessions"]
        if len(sessions) <= max_sessions:
            return 0

        # Remove oldest sessions
        to_delete = sessions[:-max_sessions]
        deleted = 0

        for entry in to_delete:
            filename = self._get_entry_field(entry, "filename", "fn")
            session_file = self.storage_dir / filename
            if session_file.exists():
                session_file.unlink()
            deleted += 1

        # Update index
        self._index["sessions"] = sessions[-max_sessions:]
        self._save_index()

        debug_log(f"Cleaned up {deleted} old sessions")
        return deleted
    
    def export_sessions(self, output_path: Path | str) -> int:
        """
        Export all sessions to a single JSON file.

        Args:
            output_path: Path to output file

        Returns:
            Number of sessions exported
        """
        output_path = Path(output_path)

        all_sessions = []
        for entry in self._index["sessions"]:
            filename = self._get_entry_field(entry, "filename", "fn")
            session_file = self.storage_dir / filename
            data = load_json_file(session_file)
            if data:
                all_sessions.append(data)

        export_data = {
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "project_directory": str(self.project_directory),
            "statistics": self.get_statistics(),
            "sessions": all_sessions,
        }

        save_json_file(output_path, export_data, pretty=True)  # Export uses pretty for readability
        debug_log(f"Exported {len(all_sessions)} sessions to: {output_path}")

        return len(all_sessions)

    def rebuild_index(self) -> dict[str, int]:
        """
        Rebuild the session index from session files (Progressive Disclosure).

        This is useful when:
        - Index is corrupted or lost
        - Migrating to a new index format
        - Recalculating statistics

        Returns:
            dict with rebuild statistics
        """
        debug_log("Rebuilding session index from session files...")

        # Find all session files
        session_files = list(self.storage_dir.glob("*.json"))
        session_files = [f for f in session_files if f.name != "index.json"]

        # Reset index
        new_index = {
            "version": 1,
            "created_at": self._index.get("created_at", datetime.now().isoformat()),
            "rebuilt_at": datetime.now().isoformat(),
            "sessions": [],
            "statistics": {
                "total_sessions": 0,
                "total_quiz_score": 0,
                "total_time_spent": 0,
            },
        }

        stats = {"sessions": 0, "errors": 0}

        for session_file in sorted(session_files):
            try:
                data = load_json_file(session_file)
                if not data:
                    stats["errors"] += 1
                    continue

                session_id = data.get("session_id", session_file.stem)
                results = data.get("results", {})
                quiz_score = results.get("quiz_score", 0)
                time_spent = results.get("time_spent", 0)

                # Add compact index entry
                new_index["sessions"].append({
                    "sid": session_id,
                    "fn": session_file.name,
                    "ts": data.get("saved_at", ""),
                    "qs": quiz_score,
                    "t": time_spent,
                    "sp": data.get("summary", "")[:50],
                })

                # Update statistics
                new_index["statistics"]["total_sessions"] += 1
                new_index["statistics"]["total_quiz_score"] += quiz_score
                new_index["statistics"]["total_time_spent"] += time_spent
                stats["sessions"] += 1

            except Exception as e:
                debug_log(f"Error reading session file {session_file}: {e}")
                stats["errors"] += 1

        self._index = new_index
        self._save_index()

        debug_log(f"Session index rebuilt: {stats}")
        return stats

    def recalculate_statistics(self) -> dict[str, Any]:
        """
        Recalculate statistics from index entries (Progressive Disclosure).

        Faster than rebuild_index() when index entries are intact.

        Returns:
            Updated statistics
        """
        total_score = 0
        total_time = 0

        for entry in self._index["sessions"]:
            total_score += self._get_entry_field(entry, "quiz_score", "qs", 0)
            total_time += self._get_entry_field(entry, "time_spent", "t", 0)

        self._index["statistics"] = {
            "total_sessions": len(self._index["sessions"]),
            "total_quiz_score": total_score,
            "total_time_spent": total_time,
        }

        self._save_index()
        debug_log(f"Statistics recalculated: {self._index['statistics']}")
        return self._index["statistics"]
