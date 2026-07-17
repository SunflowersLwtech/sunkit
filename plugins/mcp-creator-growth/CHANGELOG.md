# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-01-21

### Added
- **Progressive Disclosure**: Added `rebuild_index()`, `rebuild_keywords()`, and `compact_index()` methods to DebugIndexManager
- **Session Index Rebuild**: Added `rebuild_index()` and `recalculate_statistics()` methods to SessionStorageManager
- **Backward Compatibility**: Session storage now supports both old and new compact key formats

### Changed
- **Token Optimization**: Reduced MCP schema tokens by ~56% (from ~1150 to ~500 tokens)
  - Simplified tool docstrings to one-line descriptions
  - Removed redundant Annotated/Field descriptions
  - Moved detailed rules to SERVER_INSTRUCTIONS (sent once)
- **Compact JSON**: Default `save_json_file()` now uses compact mode (no indentation)
- **Compact Index Keys**: Session index uses shortened keys (`sid`, `fn`, `ts`, `qs`, `t`, `sp`)
- **Debug Index**: Uses compact keys (`id`, `ts`, `et`, `tags`) and compact JSON storage

### Removed
- **get_system_info tool**: Removed low-frequency utility tool to reduce schema size

### Performance
- ~28% reduction in JSON file sizes (compact mode)
- ~56% reduction in MCP schema token consumption
- Lazy keyword index rebuilding for large projects

## [1.0.0] - 2026-01-18

### Added
- Initial release
- `learning_session` - Interactive WebUI quiz for learning from AI changes
- `debug_search` - Silent RAG search for past debug solutions
- `debug_record` - Silent recording of debug experiences
- `term_get` - Programming terminology learning
- `get_system_info` - System information utility
- Project-local storage in `.mcp-sidecar/` directory
- Cross-project knowledge base in `~/.config/mcp-sidecar/`
