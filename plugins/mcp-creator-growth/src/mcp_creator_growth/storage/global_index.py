"""
Global Index Manager
====================

Manages global indexes for cross-project knowledge sharing.
Stores learned concepts and common bug patterns.
"""

from datetime import datetime
from typing import Any

from ..debug import server_debug_log as debug_log
from .path_resolver import get_global_storage_path
from .serializers import load_json_file, save_json_file


class GlobalIndexManager:
    """
    Manages global indexes across all projects.

    Storage location: ~/.config/mcp-sidecar/global/
    ├── concepts.json    # Learned concepts index
    └── bugs.json        # Global bug pattern library
    """

    def __init__(self):
        """Initialize the global index manager."""
        self.storage_dir = get_global_storage_path()
        self.concepts_file = self.storage_dir / "concepts.json"
        self.bugs_file = self.storage_dir / "bugs.json"

        # Load or create indexes
        self._concepts = self._load_concepts()
        self._bugs = self._load_bugs()

        debug_log(f"Global index manager initialized at {self.storage_dir}")

    def _load_concepts(self) -> dict[str, Any]:
        """Load concepts index or create new one."""
        data = load_json_file(self.concepts_file)
        if data:
            return data

        return {
            "version": 1,
            "created_at": datetime.now().isoformat(),
            "concepts": [],
            "by_category": {},
        }

    def _load_bugs(self) -> dict[str, Any]:
        """Load bugs index or create new one."""
        data = load_json_file(self.bugs_file)
        if data:
            return data

        return {
            "version": 1,
            "created_at": datetime.now().isoformat(),
            "patterns": [],
            "by_error_type": {},
        }

    def _save_concepts(self) -> None:
        """Save concepts index."""
        self._concepts["updated_at"] = datetime.now().isoformat()
        save_json_file(self.concepts_file, self._concepts)

    def _save_bugs(self) -> None:
        """Save bugs index."""
        self._bugs["updated_at"] = datetime.now().isoformat()
        save_json_file(self.bugs_file, self._bugs)

    def add_concept(
        self,
        name: str,
        description: str,
        category: str,
        project: str | None = None,
        examples: list[str] | None = None,
    ) -> str:
        """
        Add a learned concept to the global index.

        Args:
            name: Concept name
            description: Concept description
            category: Category (e.g., "pattern", "principle", "tool")
            project: Source project (optional)
            examples: Example code or usage (optional)

        Returns:
            Concept ID
        """
        concept_id = f"concept_{len(self._concepts['concepts']) + 1:04d}"

        concept = {
            "id": concept_id,
            "name": name,
            "description": description,
            "category": category,
            "project": project,
            "examples": examples or [],
            "added_at": datetime.now().isoformat(),
        }

        self._concepts["concepts"].append(concept)

        # Index by category
        if category not in self._concepts["by_category"]:
            self._concepts["by_category"][category] = []
        self._concepts["by_category"][category].append(concept_id)

        self._save_concepts()

        debug_log(f"Added global concept: {name}")
        return concept_id

    def get_concept(self, concept_id: str) -> dict[str, Any] | None:
        """Get a concept by ID."""
        for concept in self._concepts["concepts"]:
            if concept["id"] == concept_id:
                return concept
        return None

    def search_concepts(self, query: str) -> list[dict[str, Any]]:
        """
        Search concepts by query.

        Args:
            query: Search query

        Returns:
            List of matching concepts
        """
        query_lower = query.lower()
        results = []

        for concept in self._concepts["concepts"]:
            if (
                query_lower in concept["name"].lower()
                or query_lower in concept["description"].lower()
            ):
                results.append(concept)

        return results

    def get_concepts_by_category(self, category: str) -> list[dict[str, Any]]:
        """Get all concepts in a category."""
        concept_ids = self._concepts["by_category"].get(category, [])
        return [c for cid in concept_ids if (c := self.get_concept(cid))]

    def add_bug_pattern(
        self,
        error_type: str,
        pattern: str,
        solution: str,
        frequency: int = 1,
        tags: list[str] | None = None,
    ) -> str:
        """
        Add a bug pattern to the global library.

        Args:
            error_type: Type of error (e.g., "ImportError")
            pattern: Description of the pattern
            solution: Common solution
            frequency: How often this pattern occurs
            tags: Optional tags

        Returns:
            Pattern ID
        """
        pattern_id = f"bug_{len(self._bugs['patterns']) + 1:04d}"

        bug_pattern = {
            "id": pattern_id,
            "error_type": error_type,
            "pattern": pattern,
            "solution": solution,
            "frequency": frequency,
            "tags": tags or [],
            "added_at": datetime.now().isoformat(),
        }

        self._bugs["patterns"].append(bug_pattern)

        # Index by error type
        if error_type not in self._bugs["by_error_type"]:
            self._bugs["by_error_type"][error_type] = []
        self._bugs["by_error_type"][error_type].append(pattern_id)

        self._save_bugs()

        debug_log(f"Added global bug pattern: {error_type}")
        return pattern_id

    def get_bug_pattern(self, pattern_id: str) -> dict[str, Any] | None:
        """Get a bug pattern by ID."""
        for pattern in self._bugs["patterns"]:
            if pattern["id"] == pattern_id:
                return pattern
        return None

    def search_bug_patterns(self, error_type: str) -> list[dict[str, Any]]:
        """
        Search bug patterns by error type.

        Args:
            error_type: The error type to search for

        Returns:
            List of matching patterns
        """
        pattern_ids = self._bugs["by_error_type"].get(error_type, [])

        # Also search for partial matches
        for err_type, ids in self._bugs["by_error_type"].items():
            if error_type.lower() in err_type.lower() and err_type != error_type:
                pattern_ids.extend(ids)

        return [b for pid in pattern_ids if (b := self.get_bug_pattern(pid))]

    def get_all_concepts(self) -> list[dict[str, Any]]:
        """Get all concepts."""
        return self._concepts["concepts"]

    def get_all_bug_patterns(self) -> list[dict[str, Any]]:
        """Get all bug patterns."""
        return self._bugs["patterns"]

    def get_concept_count(self) -> int:
        """Get total number of concepts."""
        return len(self._concepts["concepts"])

    def get_bug_pattern_count(self) -> int:
        """Get total number of bug patterns."""
        return len(self._bugs["patterns"])
