"""
Storage module for MCP Learning Sidecar.
Handles persistence of debug records, learning sessions, and project metadata.
"""

from .debug_index import DebugIndexManager, DebugRecordManager
from .retrieval import DebugRetrieval, DebugSearchEngine
from .path_resolver import (
    get_storage_path,
    get_project_storage_path,
    get_global_storage_path,
    get_project_hash,
    get_global_config_dir,
    resolve_storage_priority,
)
from .serializers import (
    serialize_to_json,
    deserialize_from_json,
    save_json_file,
    load_json_file,
    serialize_session,
    deserialize_session,
)
from .global_index import GlobalIndexManager
from .project_meta import ProjectMetaManager
from .session_storage import SessionStorageManager
from .storage_manager import (
    StorageManager,
    get_storage_manager,
    list_all_projects,
    search_across_projects,
)
from .terms_index import (
    TermsIndexManager,
    get_session_terms,
    TERMS_GLOSSARY,
)

__all__ = [
    # High-level storage manager (recommended)
    "StorageManager",
    "get_storage_manager",
    "list_all_projects",
    "search_across_projects",
    # Debug index
    "DebugIndexManager",
    "DebugRecordManager",
    # Retrieval
    "DebugRetrieval",
    "DebugSearchEngine",
    # Path resolver
    "get_storage_path",
    "get_project_storage_path",
    "get_global_storage_path",
    "get_project_hash",
    "get_global_config_dir",
    "resolve_storage_priority",
    # Serializers
    "serialize_to_json",
    "deserialize_from_json",
    "save_json_file",
    "load_json_file",
    "serialize_session",
    "deserialize_session",
    # Global index
    "GlobalIndexManager",
    # Project meta
    "ProjectMetaManager",
    # Session storage
    "SessionStorageManager",
    # Terms glossary
    "TermsIndexManager",
    "get_session_terms",
    "TERMS_GLOSSARY",
]


