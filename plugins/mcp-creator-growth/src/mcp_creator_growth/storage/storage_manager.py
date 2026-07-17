"""
Storage Manager
===============

High-level storage management that integrates all storage components.
Provides unified interface for storage operations and cross-component updates.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from ..debug import server_debug_log as debug_log
from .debug_index import DebugIndexManager
from .global_index import GlobalIndexManager
from .project_meta import ProjectMetaManager
from .session_storage import SessionStorageManager
from .path_resolver import (
    get_global_config_dir,
)


class StorageManager:
    """
    Unified storage manager that coordinates all storage operations.
    
    This is the recommended high-level interface for storage operations
    as it ensures all components stay synchronized.
    """
    
    def __init__(self, project_directory: str):
        """
        Initialize the storage manager.
        
        Args:
            project_directory: The project root directory
        """
        self.project_directory = Path(project_directory).resolve()
        
        # Initialize component managers (lazy)
        self._debug_manager: DebugIndexManager | None = None
        self._session_manager: SessionStorageManager | None = None
        self._meta_manager: ProjectMetaManager | None = None
        self._global_manager: GlobalIndexManager | None = None
        
        debug_log(f"StorageManager initialized for: {self.project_directory}")
    
    @property
    def debug(self) -> DebugIndexManager:
        """Get the debug index manager (lazy loaded)."""
        if self._debug_manager is None:
            self._debug_manager = DebugIndexManager(str(self.project_directory))
        return self._debug_manager
    
    @property
    def sessions(self) -> SessionStorageManager:
        """Get the session storage manager (lazy loaded)."""
        if self._session_manager is None:
            self._session_manager = SessionStorageManager(str(self.project_directory))
        return self._session_manager
    
    @property
    def meta(self) -> ProjectMetaManager:
        """Get the project meta manager (lazy loaded)."""
        if self._meta_manager is None:
            self._meta_manager = ProjectMetaManager(str(self.project_directory))
        return self._meta_manager
    
    @property
    def global_index(self) -> GlobalIndexManager:
        """Get the global index manager (lazy loaded)."""
        if self._global_manager is None:
            self._global_manager = GlobalIndexManager()
        return self._global_manager
    
    def record_debug_experience(
        self,
        context: dict[str, Any],
        cause: str,
        solution: str,
        tags: list[str] | None = None,
        add_to_global: bool = True,
    ) -> str:
        """
        Record a debug experience with full integration.
        
        This method:
        1. Creates debug record in project storage
        2. Updates project metadata statistics
        3. Optionally adds pattern to global bug library
        
        Args:
            context: Error context dict
            cause: Root cause analysis
            solution: Solution that worked
            tags: Optional tags
            add_to_global: Whether to add to global bug patterns
            
        Returns:
            Record ID
        """
        # Record in debug index
        record_id = self.debug.record(
            context=context,
            cause=cause,
            solution=solution,
            tags=tags,
        )
        
        # Update project metadata
        self.meta.record_debug_entry(record_id)
        
        # Add to global patterns if requested
        if add_to_global:
            error_type = context.get("error_type", "Unknown")
            error_msg = context.get("error_message", "")
            
            # Create pattern from this experience
            pattern = f"{error_msg[:100]}..." if len(error_msg) > 100 else error_msg
            
            self.global_index.add_bug_pattern(
                error_type=error_type,
                pattern=pattern,
                solution=solution,
                frequency=1,
                tags=tags,
            )
        
        debug_log(f"Recorded debug experience with integration: {record_id}")
        return record_id
    
    def save_learning_session(
        self,
        session_id: str,
        session_data: dict[str, Any],
        quiz_score: int,
        time_spent: float,
        answers: list[Any] | None = None,
        add_concepts: bool = True,
    ) -> str:
        """
        Save a learning session with full integration.
        
        This method:
        1. Saves session to persistent storage
        2. Updates project metadata statistics
        3. Optionally extracts learned concepts to global index
        
        Args:
            session_id: Session identifier
            session_data: Full session data
            quiz_score: Quiz score
            time_spent: Time spent in seconds
            answers: Quiz answers
            add_concepts: Whether to extract concepts
            
        Returns:
            Path to saved session file
        """
        # Save session
        session_path = self.sessions.save_session(
            session_id=session_id,
            session_data=session_data,
            quiz_score=quiz_score,
            time_spent=time_spent,
            answers=answers,
        )
        
        # Project metadata is already updated by SessionStorageManager
        
        # Extract concepts if requested
        if add_concepts:
            focus_areas = session_data.get("focus_areas", [])
            summary = session_data.get("summary", "")
            
            for area in focus_areas:
                self.global_index.add_concept(
                    name=f"Learning: {area}",
                    description=summary[:200] if summary else "Learning session concept",
                    category=area,
                    project=str(self.project_directory),
                )
        
        debug_log(f"Saved learning session with integration: {session_id}")
        return session_path
    
    def search_all_debug(
        self,
        query: str,
        include_global: bool = True,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Search debug experiences from both project and global sources.
        
        Args:
            query: Search query
            include_global: Whether to search global patterns
            limit: Maximum results per source
            
        Returns:
            Dict with 'project' and 'global' results
        """
        from .retrieval import DebugRetrieval
        
        results = {
            "project": [],
            "global": [],
            "total_count": 0,
        }
        
        # Search project records
        retrieval = DebugRetrieval(index_manager=self.debug)
        project_results = retrieval.search(query=query, limit=limit)
        results["project"] = project_results
        
        # Search global patterns
        global_count = 0
        if include_global:
            # Extract error type from query if possible
            global_patterns = self.global_index.search_bug_patterns(query)
            sliced_global = global_patterns[:limit]
            results["global"] = sliced_global
            global_count = len(sliced_global)
        
        results["total_count"] = len(project_results) + global_count
        
        return results
    
    def get_project_summary(self) -> dict[str, Any]:
        """
        Get a comprehensive summary of project storage.
        
        Returns:
            Summary dict with statistics and recent activity
        """
        meta = self.meta.get_metadata()
        stats = self.meta.get_statistics()
        
        return {
            "project_name": meta.get("project_name"),
            "project_hash": meta.get("project_hash"),
            "statistics": {
                "learning_sessions": stats.get("learning_sessions", 0),
                "debug_records": stats.get("debug_records", 0),
                "average_quiz_score": self.meta.get_average_quiz_score(),
                "total_learning_time_hours": stats.get("total_learning_time", 0) / 3600,
            },
            "recent": {
                "last_session": meta.get("last_learning_session"),
                "last_debug": meta.get("last_debug_record"),
            },
            "storage": {
                "sessions_count": self.sessions.get_statistics().get("total_sessions", 0),
                "debug_count": self.debug.get_record_count(),
            },
        }
    
    def export_all(self, output_path: Path | str) -> dict[str, Any]:
        """
        Export all project data to a single file.
        
        Args:
            output_path: Path to output file (JSON)
            
        Returns:
            Export summary
        """
        from .serializers import save_json_file
        
        output_path = Path(output_path)

        # Gather all data with explicit type annotations
        debug_records: list[dict[str, Any]] = self.debug.list_records()
        sessions: list[dict[str, Any]] = self.sessions.list_sessions(limit=1000)

        export_data = {
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "project_directory": str(self.project_directory),
            "metadata": self.meta.get_metadata(),
            "debug_records": debug_records,
            "sessions": sessions,
        }

        save_json_file(output_path, export_data)

        return {
            "success": True,
            "path": str(output_path),
            "debug_count": len(debug_records),
            "session_count": len(sessions),
        }
    
    def cleanup(
        self,
        max_sessions: int = 100,
        max_debug_age_days: int | None = None,
    ) -> dict[str, int]:
        """
        Cleanup old storage data.
        
        Args:
            max_sessions: Maximum sessions to keep
            max_debug_age_days: Optional max age for debug records
            
        Returns:
            Cleanup summary with counts
        """
        cleaned = {
            "sessions_removed": 0,
            "debug_removed": 0,
        }
        
        # Cleanup sessions
        cleaned["sessions_removed"] = self.sessions.cleanup_old_sessions(max_sessions)
        
        # Debug cleanup would need age filter (future enhancement)
        # For now, just report
        debug_log(f"Storage cleanup complete: {cleaned}")
        
        return cleaned


def get_storage_manager(project_directory: str) -> StorageManager:
    """
    Factory function to get a StorageManager instance.
    
    Args:
        project_directory: Project directory path
        
    Returns:
        StorageManager instance
    """
    return StorageManager(project_directory)


def list_all_projects() -> list[dict[str, Any]]:
    """
    List all known projects from global storage.
    
    Returns:
        List of project info dicts
    """
    global_dir = get_global_config_dir()
    projects_dir = global_dir / "projects"
    
    if not projects_dir.exists():
        return []
    
    projects = []
    for project_hash_dir in projects_dir.iterdir():
        if project_hash_dir.is_dir():
            meta_file = project_hash_dir / "meta.json"
            if meta_file.exists():
                from .serializers import load_json_file
                meta = load_json_file(meta_file)
                if meta:
                    projects.append({
                        "hash": project_hash_dir.name,
                        "name": meta.get("project_name", "Unknown"),
                        "path": meta.get("project_path", ""),
                        "last_updated": meta.get("updated_at"),
                    })
    
    return projects


def search_across_projects(query: str, limit_per_project: int = 5) -> list[dict[str, Any]]:
    """
    Search debug experiences across all known projects.
    
    Args:
        query: Search query
        limit_per_project: Max results per project
        
    Returns:
        List of results with project info
    """
    all_results = []
    
    for project in list_all_projects():
        project_path = project.get("path")
        if not project_path or not Path(project_path).exists():
            continue
        
        try:
            manager = get_storage_manager(project_path)
            results = manager.search_all_debug(
                query=query,
                include_global=False,
                limit=limit_per_project,
            )
            
            for record in results.get("project", []):
                record["_project_name"] = project.get("name")
                record["_project_path"] = project_path
                all_results.append(record)
                
        except Exception as e:
            debug_log(f"Error searching project {project_path}: {e}")
    
    return all_results
